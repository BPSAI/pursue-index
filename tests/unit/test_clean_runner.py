"""Tests for the per-card cleanup runner.

End-to-end at the file level: feeds a mock ``pages.jsonl``, drives the
cleanup client (mocked), asserts on the sidecar JSONL contents,
idempotency-key skips, and the budget-cap abort path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pursue_index.clean import client as clean_client
from pursue_index.clean import runner


def _write_pages(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _fake_clean(text: str, usage: clean_client.Usage):
    """Build a stub clean_page callable that returns fixed text + usage."""
    def _fn(raw_text: str, model_id: str) -> tuple[str, clean_client.Usage]:
        return text, usage
    return _fn


def test_run_card_writes_sidecar_for_every_input_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two input pages → two sidecar rows with model_id + sha provenance."""
    pages_path = tmp_path / "cardA" / "pages.jsonl"
    _write_pages(
        pages_path,
        [
            {"page": 1, "text": "raw page one", "confidence": 90, "engine": "surya"},
            {"page": 2, "text": "raw page two", "confidence": 88, "engine": "surya"},
        ],
    )
    sidecar_path = tmp_path / "cardA" / "pages_cleaned.jsonl"

    usage = clean_client.Usage(
        input_tokens=100, output_tokens=80, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    monkeypatch.setattr(runner, "clean_page", _fake_clean("CLEANED", usage))

    report = runner.run_card(
        card_id="cardA",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    assert len(rows) == 2
    for row in rows:
        assert row["card_id"] == "cardA"
        assert row["text_cleaned"] == "CLEANED"
        assert row["model_id"] == "claude-haiku-4-5-20251001"
        assert len(row["prompt_sha256"]) == 64
        assert len(row["input_sha256"]) == 64
        assert len(row["output_sha256"]) == 64
        assert "generated_at" in row
    assert report.pages_cleaned == 2
    assert report.pages_skipped == 0


def test_run_card_skips_pages_already_in_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running with an unchanged input.jsonl is a no-op (full skip)."""
    from pursue_index.clean import prompt as clean_prompt

    pages_path = tmp_path / "cardB" / "pages.jsonl"
    _write_pages(pages_path, [{"page": 1, "text": "same text"}])
    sidecar_path = tmp_path / "cardB" / "pages_cleaned.jsonl"
    # Seed the sidecar with a row whose input_sha256 + model + prompt all
    # match — the only path that should produce a skip after the
    # idempotency tightening.
    seed_row = {
        "page": 1,
        "card_id": "cardB",
        "text_cleaned": "previously cleaned",
        "input_sha256": clean_prompt.input_sha256("same text"),
        "model_id": "claude-haiku-4-5-20251001",
        "prompt_sha256": clean_prompt.prompt_sha256(),
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(seed_row) + "\n")

    calls: list[str] = []

    def _trip(_: str, __: str) -> tuple[str, clean_client.Usage]:
        calls.append("should not run")
        raise AssertionError("clean_page must not be invoked on a skip")

    monkeypatch.setattr(runner, "clean_page", _trip)

    report = runner.run_card(
        card_id="cardB",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    assert calls == []
    assert report.pages_cleaned == 0
    assert report.pages_skipped == 1


def test_run_card_does_not_skip_when_prompt_sha256_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a prompt bump must invalidate
    cached rows even when ``input_sha256`` matches.

    Prior behaviour was to skip on input-sha-only match, so a prompt
    revision would silently reuse stale cleaned text. The runner now
    checks ``model_id`` + ``prompt_sha256`` against the row before
    declaring a skip.
    """
    from pursue_index.clean import prompt as clean_prompt

    pages_path = tmp_path / "cardP" / "pages.jsonl"
    _write_pages(pages_path, [{"page": 1, "text": "same text"}])
    sidecar_path = tmp_path / "cardP" / "pages_cleaned.jsonl"
    seed_row = {
        "page": 1,
        "card_id": "cardP",
        "text_cleaned": "previously cleaned",
        "input_sha256": clean_prompt.input_sha256("same text"),
        "model_id": "claude-haiku-4-5-20251001",
        # Stale prompt_sha — does NOT match the current canonical prompt.
        "prompt_sha256": "0" * 64,
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(seed_row) + "\n")

    usage = clean_client.Usage(
        input_tokens=10, output_tokens=10, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    monkeypatch.setattr(runner, "clean_page", _fake_clean("RECLEANED", usage))
    report = runner.run_card(
        card_id="cardP",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    assert report.pages_cleaned == 1
    assert report.pages_skipped == 0


def test_run_card_aborts_when_running_cost_exceeds_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget cap is a hard stop — raises BudgetExceededError mid-card."""
    pages_path = tmp_path / "cardC" / "pages.jsonl"
    _write_pages(
        pages_path,
        [
            {"page": 1, "text": "p1"},
            {"page": 2, "text": "p2"},
            {"page": 3, "text": "p3"},
        ],
    )
    sidecar_path = tmp_path / "cardC" / "pages_cleaned.jsonl"
    # Each call costs $0.50 (well above any sane cap). The second call must
    # raise BudgetExceededError without ever invoking clean_page a third time.
    expensive = clean_client.Usage(
        input_tokens=500_000, output_tokens=0, cache_read_tokens=0,
        cache_creation_tokens=0,
    )

    call_count = {"n": 0}

    def _fn(raw_text: str, model_id: str) -> tuple[str, clean_client.Usage]:
        call_count["n"] += 1
        return "out", expensive

    monkeypatch.setattr(runner, "clean_page", _fn)

    with pytest.raises(runner.BudgetExceededError):
        runner.run_card(
            card_id="cardC",
            pages_path=pages_path,
            sidecar_path=sidecar_path,
            model_id="claude-haiku-4-5-20251001",
            budget_usd=0.50,
            running_cost_usd=0.0,
        )
    # After the first cleaned page, running cost = $0.40 — still under the
    # $0.50 cap, so the second call runs and pushes us over. The third
    # call must NOT happen.
    assert call_count["n"] == 2


def test_budget_exceeded_error_carries_partial_card_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Follow-up: when the runner raises mid-card, the in-progress
    card has already incurred N pages of cost on the sidecar. The exception
    must surface that partial spend (``partial_cost_usd``) and the
    in-progress card id so the CLI can fold it into the running total
    before printing the abort summary. Otherwise the summary under-reports
    spend and the operator may overspend on the next invocation.
    """
    pages_path = tmp_path / "cardP" / "pages.jsonl"
    _write_pages(
        pages_path,
        [
            {"page": 1, "text": "p1"},
            {"page": 2, "text": "p2"},
            {"page": 3, "text": "p3"},
        ],
    )
    sidecar_path = tmp_path / "cardP" / "pages_cleaned.jsonl"
    # $0.40 per call: after the first call cost = $0.40, after second = $0.80
    # which trips the $0.50 cap. Partial-card spend should be ~$0.80.
    expensive = clean_client.Usage(
        input_tokens=500_000, output_tokens=0, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    monkeypatch.setattr(runner, "clean_page", _fake_clean("out", expensive))

    with pytest.raises(runner.BudgetExceededError) as excinfo:
        runner.run_card(
            card_id="cardP",
            pages_path=pages_path,
            sidecar_path=sidecar_path,
            model_id="claude-haiku-4-5-20251001",
            budget_usd=0.50,
            running_cost_usd=0.0,
        )
    exc = excinfo.value
    # Partial spend = both pages cleaned before the cap trip ($0.80).
    assert exc.partial_cost_usd > 0.0
    assert exc.partial_cost_usd == pytest.approx(0.80, abs=0.01)
    assert exc.card_id == "cardP"
    # And the in-progress page count is surfaced so the CLI can append a
    # partial CardReport row to the summary.
    assert exc.pages_cleaned == 2


def test_run_card_falls_back_when_cleaned_output_is_too_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model returning a refusal or near-empty
    string would clobber valid OCR. Guard: ratio < 0.2 → keep raw OCR
    text, flag the row as ``cleanup_skipped="length_divergence"``.
    """
    pages_path = tmp_path / "cardS" / "pages.jsonl"
    raw = "This is a long-enough OCR page with several sentences." * 5
    _write_pages(pages_path, [{"page": 1, "text": raw}])
    sidecar_path = tmp_path / "cardS" / "pages_cleaned.jsonl"

    usage = clean_client.Usage(
        input_tokens=100, output_tokens=10, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    # Model returns a refusal — far below the 0.2 ratio threshold.
    monkeypatch.setattr(
        runner, "clean_page", _fake_clean("I cannot.", usage),
    )
    report = runner.run_card(
        card_id="cardS",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    assert len(rows) == 1
    assert rows[0]["text_cleaned"] == raw  # Raw OCR preserved
    assert rows[0]["cleanup_skipped"] == "length_divergence"
    # The page still counts as "cleaned" for accounting (LLM was called),
    # but downstream consumers (build_pages_cleaned) will treat it as a
    # skipped row — see cycle 3.
    assert report.pages_cleaned == 1


def test_run_card_falls_back_when_cleaned_output_is_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mirror of the short-divergence case: ratio > 2.0 → keep raw OCR."""
    pages_path = tmp_path / "cardL" / "pages.jsonl"
    raw = "Short OCR page."
    _write_pages(pages_path, [{"page": 1, "text": raw}])
    sidecar_path = tmp_path / "cardL" / "pages_cleaned.jsonl"

    usage = clean_client.Usage(
        input_tokens=100, output_tokens=300, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    # Model returns a long preamble + the text — way over 2x.
    long_output = "Here is the cleaned OCR text you requested: " * 20 + raw
    monkeypatch.setattr(
        runner, "clean_page", _fake_clean(long_output, usage),
    )
    runner.run_card(
        card_id="cardL",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    assert rows[0]["text_cleaned"] == raw
    assert rows[0]["cleanup_skipped"] == "length_divergence"


def test_run_card_keeps_cleaned_output_when_ratio_is_in_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ratio in [0.2, 2.0] → cleaned text is kept, no flag set."""
    pages_path = tmp_path / "cardK" / "pages.jsonl"
    raw = "Some OCR text with a few errrs and broken-\nhyphens."
    _write_pages(pages_path, [{"page": 1, "text": raw}])
    sidecar_path = tmp_path / "cardK" / "pages_cleaned.jsonl"

    usage = clean_client.Usage(
        input_tokens=20, output_tokens=20, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    monkeypatch.setattr(
        runner, "clean_page",
        _fake_clean("Some OCR text with a few errors and broken hyphens.", usage),
    )
    runner.run_card(
        card_id="cardK",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    assert "cleanup_skipped" not in rows[0]
    assert rows[0]["text_cleaned"] != raw  # Cleaned version kept


def test_run_card_skips_empty_ocr_pages_without_calling_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty raw OCR text is empty-in/empty-out, not a length
    divergence. Special-case at the top of the per-page loop: don't call
    the model, write a sidecar row flagged ``cleanup_skipped="empty_input"``,
    and count the page as skipped (not cleaned).

    Why: empty pages used to trip the [0.2, 2.0] length-divergence guard
    (``len('') / max(len(''), 1) == 0``), which mis-flagged them as
    refusals. The provenance was misleading AND we burned a model call
    on a guaranteed-empty result.
    """
    pages_path = tmp_path / "cardE" / "pages.jsonl"
    _write_pages(
        pages_path,
        [
            {"page": 1, "text": "", "confidence": 0, "engine": "surya"},
            {"page": 2, "text": "   \n  ", "confidence": 0, "engine": "surya"},
        ],
    )
    sidecar_path = tmp_path / "cardE" / "pages_cleaned.jsonl"

    def _trip(*args: object, **kwargs: object) -> tuple[str, clean_client.Usage]:
        raise AssertionError("clean_page must NOT be called on empty pages")

    monkeypatch.setattr(runner, "clean_page", _trip)

    report = runner.run_card(
        card_id="cardE",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    assert len(rows) == 2
    for row in rows:
        assert row["cleanup_skipped"] == "empty_input"
        assert row["text_cleaned"] == ""  # empty in → empty out
    # Empty pages are skipped, not cleaned (no LLM call billed).
    assert report.pages_cleaned == 0
    assert report.pages_skipped == 2


def test_run_card_writes_content_filter_skip_row_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Anthropic's content filter blocks one page, the runner must:

      1. Catch ``ContentFilteredError`` so the pilot does not crash
         mid-card (interrupted a May 2026 pilot on a charged page;
         card <redacted> page <redacted>).
      2. Write a sidecar row flagged ``cleanup_skipped="content_filter"``
         with empty ``text_cleaned`` — the raw OCR is preserved in
         ``pages.jsonl`` and the build script will keep this row for
         page-coverage alignment without shipping raw OCR under the
         "cleaned" label.
      3. Continue to the next page so the rest of the card cleans
         normally.

    Content-filter rejections also do not bill (the API rejects before
    returning output), so the page is counted as ``skipped``, not
    ``cleaned`` — mirrors the ``empty_input`` accounting.
    """
    from pursue_index.clean import client as clean_client_mod

    pages_path = tmp_path / "cardCF" / "pages.jsonl"
    _write_pages(
        pages_path,
        [
            {"page": 1, "text": "first page, cleans fine"},
            {"page": 2, "text": "page that trips the filter"},
            {"page": 3, "text": "third page, cleans fine"},
        ],
    )
    sidecar_path = tmp_path / "cardCF" / "pages_cleaned.jsonl"

    ok_usage = clean_client.Usage(
        input_tokens=50, output_tokens=50, cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    call_log: list[int] = []

    def _fn(raw_text: str, model_id: str) -> tuple[str, clean_client.Usage]:
        call_log.append(len(raw_text))
        if "trips the filter" in raw_text:
            raise clean_client_mod.ContentFilteredError(
                "Output blocked by content filtering policy",
                request_id="req_test_001",
            )
        return "CLEANED", ok_usage

    monkeypatch.setattr(runner, "clean_page", _fn)

    report = runner.run_card(
        card_id="cardCF",
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0,
        running_cost_usd=0.0,
    )
    rows = list(_iter_jsonl(sidecar_path))
    # Three rows out: one normal-cleaned + one content_filter skip + one
    # normal-cleaned. The runner did NOT crash on the filtered page.
    assert len(rows) == 3
    by_page = {row["page"]: row for row in rows}
    assert by_page[1]["text_cleaned"] == "CLEANED"
    assert "cleanup_skipped" not in by_page[1]
    # Skip row: empty cleaned text, content_filter flag set, raw OCR
    # never shipped under the "cleaned" label.
    assert by_page[2]["cleanup_skipped"] == "content_filter"
    assert by_page[2]["text_cleaned"] == ""
    # Page 3 cleaned normally — proving the runner did not abort.
    assert by_page[3]["text_cleaned"] == "CLEANED"
    assert "cleanup_skipped" not in by_page[3]
    # Accounting: filtered page does not count as cleaned (no model
    # billing accrued) — mirrors how ``empty_input`` is bucketed.
    assert report.pages_cleaned == 2
    assert report.pages_skipped == 1
    # All three input pages were visited (the filter trip didn't short-
    # circuit the loop).
    assert len(call_log) == 3


def _capture_runner_warnings(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch ``runner.log.warning`` to append to a captured list."""
    captured: list[dict[str, Any]] = []

    def fake_warning(event: str, **kw: Any) -> None:
        captured.append({"event": event, **kw})

    monkeypatch.setattr(runner.log, "warning", fake_warning)
    return captured


def test_run_card_logs_request_id_at_runner_site_on_content_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner-site warning binds ``request_id`` from
    the exception so post-mortem correlation between (card_id, page)
    and the Anthropic-side log happens in a single log scope.

    The client already logs ``clean.llm.content_filtered`` with the
    request_id at the SDK boundary; the runner's additional warning
    binds card_id + page + request_id together for operators acting
    on a public-pilot incident without joining across log streams.
    """
    from pursue_index.clean import client as clean_client_mod

    pages_path = tmp_path / "cardCF" / "pages.jsonl"
    _write_pages(pages_path, [{"page": 1, "text": "filtered page"}])
    sidecar_path = tmp_path / "cardCF" / "pages_cleaned.jsonl"

    def _fn(raw_text: str, model_id: str) -> tuple[str, clean_client.Usage]:
        raise clean_client_mod.ContentFilteredError(
            "Anthropic content filter declined cleaned output",
            request_id="req_test_logger_bound",
        )

    monkeypatch.setattr(runner, "clean_page", _fn)
    captured = _capture_runner_warnings(monkeypatch)

    runner.run_card(
        card_id="cardCF", pages_path=pages_path, sidecar_path=sidecar_path,
        model_id="claude-haiku-4-5-20251001",
        budget_usd=10.0, running_cost_usd=0.0,
    )

    cf_events = [e for e in captured if e["event"] == "clean.page.content_filtered"]
    assert cf_events, f"expected runner-site warning; got: {captured}"
    e = cf_events[0]
    assert e["card_id"] == "cardCF"
    assert e["page"] == 1
    assert e["request_id"] == "req_test_logger_bound"


def _iter_jsonl(path: Path):
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
