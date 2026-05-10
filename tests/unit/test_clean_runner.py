"""Tests for the per-card cleanup runner.

End-to-end at the file level: feeds a mock ``pages.jsonl``, drives the
cleanup client (mocked), asserts on the sidecar JSONL contents,
idempotency-key skips, and the budget-cap abort path.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    """Regression for nayru P1 / Codex P1: a prompt bump must invalidate
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


def test_run_card_falls_back_when_cleaned_output_is_too_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """nayru P1 / laverna SEC-001: model returning a refusal or near-empty
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
    """Codex P2: empty raw OCR text is empty-in/empty-out, not a length
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


def _iter_jsonl(path: Path):
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
