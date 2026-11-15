"""Tests for the OCR benchmark harness's addendum-candidate support.

Issue #39: the v3 bake-off gets a ``claude-sonnet-5-5`` addendum. These
tests pin two things: (1) the harness actually dispatches the new
candidate's pages through the right model, with its results flowing into
the report alongside the pre-existing engines, and (2) ``--dry-run``
prints a per-candidate cost projection for the v3 document set without
constructing an Anthropic client — no live run, no spend.

The Anthropic SDK is faked throughout; nothing here makes a network call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _ocr_benchmark_candidates as obcands  # noqa: E402
import _ocr_benchmark_llm as obl  # noqa: E402
import _ocr_metrics as om  # noqa: E402
import build_ocr_report as br  # noqa: E402
import run_ocr_benchmark as rb  # noqa: E402

from pursue_index.ocr import llm as ocr_llm  # noqa: E402

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "ocr_three_page.pdf"


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessage:
    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeContentBlock(text)]
        self.usage = usage


class _FakeMessages:
    def __init__(self, reply_text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._reply_text = reply_text

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return _FakeMessage(self._reply_text, _FakeUsage(1200, 400))


class _FakeAnthropic:
    def __init__(self, reply_text: str = '{"text": "page text", "confidence": 90}') -> None:
        self.messages = _FakeMessages(reply_text)


# ---------------------------------------------------------------------------
# candidate registry
# ---------------------------------------------------------------------------
def test_sonnet_5_5_is_an_addendum_candidate() -> None:
    names = [c.name for c in rb.ADDENDUM_CANDIDATES]
    assert "sonnet-5-5" in names
    candidate = next(c for c in rb.ADDENDUM_CANDIDATES if c.name == "sonnet-5-5")
    assert candidate.model == "claude-sonnet-5-5"


# ---------------------------------------------------------------------------
# AC1 — with a fake client, the harness runs the candidate over a fixture
# document and the report includes it alongside the existing candidates.
# ---------------------------------------------------------------------------
def test_run_llm_candidate_dispatches_fixture_pages_under_its_own_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pdf2image import convert_from_path

    images = convert_from_path(str(FIXTURE_PDF), dpi=72)
    fake_client = _FakeAnthropic()
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: fake_client)

    candidate = next(c for c in rb.ADDENDUM_CANDIDATES if c.name == "sonnet-5-5")
    rows = rb.run_llm_candidate(images, candidate, cache_root=tmp_path)

    assert len(rows) == len(images) == 3
    assert all(r["text"] == "page text" for r in rows)
    assert all(r["cost_usd"] > 0 for r in rows)
    assert len(fake_client.messages.calls) == 3
    assert all(call["model"] == "claude-sonnet-5-5" for call in fake_client.messages.calls)


def test_run_llm_candidate_restores_model_and_cache_dir_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pdf2image import convert_from_path

    images = convert_from_path(str(FIXTURE_PDF), dpi=72)[:1]
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _FakeAnthropic())

    original_model = rb.settings.ocr_llm_model
    original_cache_dir = ocr_llm._cache_dir
    candidate = next(c for c in rb.ADDENDUM_CANDIDATES if c.name == "sonnet-5-5")

    rb.run_llm_candidate(images, candidate, cache_root=tmp_path)

    assert rb.settings.ocr_llm_model == original_model
    assert ocr_llm._cache_dir is original_cache_dir


def test_report_includes_new_candidate_alongside_existing_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pdf2image import convert_from_path

    images = convert_from_path(str(FIXTURE_PDF), dpi=72)
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _FakeAnthropic())
    candidate = next(c for c in rb.ADDENDUM_CANDIDATES if c.name == "sonnet-5-5")
    rows = rb.run_llm_candidate(images, candidate, cache_root=tmp_path)

    card = {
        "card_id": "fixture-card",
        "category": "test",
        "description": "fixture",
        "pdf_filename": FIXTURE_PDF.name,
        "engines": {
            "tesseract": [
                {"page": i + 1, "text": "t", "confidence": 80.0, "wall_clock_s": 0.1, "cost_usd": 0.0}
                for i in range(3)
            ],
            "surya": [
                {"page": i + 1, "text": "s", "confidence": 85.0, "wall_clock_s": 0.1, "cost_usd": 0.0}
                for i in range(3)
            ],
            "llm": [
                {"page": i + 1, "text": "truth", "confidence": 95.0, "wall_clock_s": 0.1,
                 "cost_usd": 0.001, "tokens": {}}
                for i in range(3)
            ],
            "llm_candidates": {"sonnet-5-5": rows},
        },
    }

    agg = om.compute_metrics([card])
    candidate_agg = om.compute_candidate_metrics([card])
    table = br.render_summary_table(agg, [], candidate_agg=candidate_agg)

    assert "sonnet-5-5" in table
    assert "Tesseract" in table
    assert "Surya" in table


# ---------------------------------------------------------------------------
# AC2 — --dry-run prints a per-candidate cost estimate for the v3 document
# set and makes no API call.
# ---------------------------------------------------------------------------
def test_dry_run_prints_per_candidate_estimate_without_api_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _must_not_be_called() -> Any:
        raise AssertionError("dry-run must not construct an Anthropic client")

    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", _must_not_be_called)

    result = rb.main(["--dry-run"])

    out = capsys.readouterr().out
    assert result is None
    assert "sonnet-5-5" in out
    assert "haiku-4-5" in out
    assert "$" in out


def test_estimate_candidate_cost_is_pure_math_over_the_golden_set() -> None:
    import _ocr_benchmark_candidates as obc

    candidate = obc.Candidate("x", "model-x", price_input_per_m=2.0,
                               price_output_per_m=10.0, price_cache_read_per_m=0.2)
    cost = obc.estimate_candidate_cost(candidate, pages=10)
    expected = 10 * (
        obc.EST_INPUT_TOKENS_PER_PAGE / 1_000_000 * 2.0
        + obc.EST_OUTPUT_TOKENS_PER_PAGE / 1_000_000 * 10.0
    )
    assert cost == pytest.approx(expected)


def test_live_run_accepts_key_from_settings_not_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 'put it in .env' hint is true: a settings-only key passes the gate."""
    from pydantic import SecretStr

    from pursue_index.config import settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr("dummy-settings-key"))
    monkeypatch.setattr(rb, "parse_golden", lambda: [])
    monkeypatch.setattr(rb, "missing_engines", lambda: [])
    monkeypatch.setattr(rb.settings, "ocr_llm_model", "claude-haiku-4-5")
    monkeypatch.setattr(rb, "load_manifest", lambda p: (_ for _ in ()).throw(RuntimeError("past-gate")))
    with pytest.raises(RuntimeError, match="past-gate"):
        rb.main([])


# ---------------------------------------------------------------------------
# #198 — price from the invoked model, a hard spend cap, engines checked first
# ---------------------------------------------------------------------------
def _images(n: int) -> list:
    from pdf2image import convert_from_path

    return convert_from_path(str(FIXTURE_PDF), dpi=72)[:n]


def test_the_truth_pass_is_priced_at_the_resolved_models_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _FakeAnthropic())
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path)
    truth = rb.candidate_for_model("claude-sonnet-4-6")
    rows = obl.run_llm(_images(1), truth)
    # 1200 input and 400 output tokens at $3 and $15 per million, not Haiku's $1 and $5.
    assert rows[0]["cost_usd"] == pytest.approx(1200 / 1e6 * 3.0 + 400 / 1e6 * 15.0)


def test_an_unpriced_model_is_refused() -> None:
    with pytest.raises(SystemExit, match="no price for model 'claude-unknown'"):
        rb.candidate_for_model("claude-unknown")


def test_main_refuses_an_unpriced_resolved_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb, "parse_golden", lambda: [])
    monkeypatch.setattr(rb.settings, "ocr_llm_model", "claude-unknown")
    with pytest.raises(SystemExit, match="no price"):
        rb.main([])


def test_the_budget_refuses_a_call_that_could_pass_the_cap() -> None:
    budget = rb.Budget(cap_usd=0.01)
    budget.reserve(0.01)  # exactly at the cap is allowed
    budget.add(0.008)
    with pytest.raises(rb.CapReachedError, match="hard cap"):
        budget.reserve(0.003)
    rb.Budget().reserve(1e9)  # no cap, never refused


def test_run_llm_stops_before_the_call_that_would_pass_the_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeAnthropic()
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: fake)
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(obl, "LLM_CALL_DELAY_S", 0)
    truth = rb.candidate_for_model("claude-haiku-4-5")
    per_page = obcands.estimate_candidate_cost(truth, 1)
    with pytest.raises(rb.CapReachedError):
        obl.run_llm(_images(3), truth, rb.Budget(cap_usd=per_page * 0.5))
    assert fake.messages.calls == []  # refused before any paid call
    budget = rb.Budget(cap_usd=per_page * 1.5)
    with pytest.raises(rb.CapReachedError):
        obl.run_llm(_images(3), truth, budget)
    assert len(fake.messages.calls) == 1
    assert budget.spent_usd > 0


def test_a_hard_cap_must_be_finite_and_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb, "parse_golden", lambda: [])
    for bad in ("0", "-1", "nan", "inf"):
        with pytest.raises(SystemExit) as exc:
            rb.main(["--hard-cap-usd", bad])
        assert exc.value.code == 2, bad


def test_a_run_stopped_on_the_cap_says_so_and_keeps_finished_cards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datetime import UTC, datetime

    calls: list[str] = []

    def fake_card(card_id, entry, manifest, truth, budget):
        calls.append(card_id)
        if len(calls) == 2:
            raise rb.CapReachedError("stopped on the hard cap: test")
        return {"card_id": card_id}

    monkeypatch.setattr(rb, "benchmark_card", fake_card)
    monkeypatch.setattr(rb, "OUT_DIR", tmp_path)
    golden = [{"card_id": c} for c in ("a", "b", "c")]
    truth = rb.candidate_for_model("claude-sonnet-4-6")
    out = rb._run_all(golden, None, truth, rb.Budget(cap_usd=1.0), datetime.now(UTC))
    payload = json.loads(out.read_text())
    assert calls == ["a", "b"]
    assert [r["card_id"] for r in payload["results"]] == ["a"]
    assert payload["stopped_on_cap"] == (
        "stopped on the hard cap: test (during card b, which is not in results)")
    assert payload["llm_model"] == "claude-sonnet-4-6"
    assert payload["llm_pricing"]["input_per_m"] == 3.0
    assert payload["hard_cap_usd"] == 1.0
    assert not list(tmp_path.glob("_checkpoint-*"))


def test_missing_engines_names_each_one() -> None:
    assert rb.missing_engines(find_spec=lambda name: object(), which=lambda name: "/bin/x") == []
    problems = rb.missing_engines(find_spec=lambda name: None, which=lambda name: None)
    assert [p.split(":")[0] for p in problems] == ["surya", "tesseract"]


def test_main_refuses_at_startup_when_an_engine_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rb, "parse_golden", lambda: [])
    monkeypatch.setattr(rb.settings, "ocr_llm_model", "claude-haiku-4-5")
    monkeypatch.setattr(rb, "missing_engines", lambda: ["surya: not installed"])
    monkeypatch.setattr(rb, "load_manifest", lambda p: pytest.fail("ran past the engine check"))
    with pytest.raises(SystemExit, match="surya: not installed"):
        rb.main([])


def test_the_engine_listing_names_each_model_and_its_per_page_cost() -> None:
    text = rb.engine_lines(rb.candidate_for_model("claude-sonnet-4-6"), 2.5)
    assert "claude-sonnet-4-6" in text and "claude-sonnet-5-5" in text
    assert "/page" in text and "hard cap: $2.5000" in text


def test_the_budget_checks_against_the_costliest_call_so_far() -> None:
    budget = rb.Budget(cap_usd=0.05)
    budget.add(0.03)  # a dense page cost far more than its estimate
    with pytest.raises(rb.CapReachedError, match=r"could cost \$0\.0300"):
        budget.reserve(0.001)


def test_a_call_that_raises_is_charged_its_estimate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(img, candidate):
        raise RuntimeError("billed, then failed")

    monkeypatch.setattr(obl, "_llm_one", boom)
    truth = rb.candidate_for_model("claude-haiku-4-5")
    budget = rb.Budget(cap_usd=1.0)
    with pytest.raises(RuntimeError, match="billed"):
        obl.run_llm(_images(1), truth, budget)
    assert budget.spent_usd == pytest.approx(obcands.estimate_candidate_cost(truth, 1))


def test_cache_writes_are_priced() -> None:
    truth = rb.candidate_for_model("claude-sonnet-4-6")
    cost = obl._llm_cost({"cache_creation": 1_000_000}, truth)
    assert cost == pytest.approx(3.0 * 1.25)


def test_a_billed_failure_is_charged_its_real_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    def billed_then_failed(img, candidate):
        exc = RuntimeError("parse failed after billing")
        exc.benchmark_cost_usd = 0.25  # type: ignore[attr-defined]
        raise exc

    monkeypatch.setattr(obl, "_llm_one", billed_then_failed)
    budget = rb.Budget(cap_usd=10.0)
    with pytest.raises(RuntimeError):
        obl.run_llm(_images(1), rb.candidate_for_model("claude-haiku-4-5"), budget)
    assert budget.spent_usd == pytest.approx(0.25)


def test_an_unbilled_failure_is_charged_the_costliest_call_so_far(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(img, candidate):
        raise RuntimeError("no response")

    monkeypatch.setattr(obl, "_llm_one", boom)
    budget = rb.Budget(cap_usd=10.0)
    budget.add(0.5)
    with pytest.raises(RuntimeError):
        obl.run_llm(_images(1), rb.candidate_for_model("claude-haiku-4-5"), budget)
    assert budget.spent_usd == pytest.approx(1.0)


def test_a_billed_response_that_fails_to_parse_carries_its_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: _FakeAnthropic())
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path)

    def bad_parse(raw):
        raise ValueError("unparseable")

    monkeypatch.setattr(ocr_llm, "parse_response", bad_parse)
    truth = rb.candidate_for_model("claude-sonnet-4-6")
    with pytest.raises(ValueError) as exc:
        obl._llm_one(_images(1)[0], truth)
    assert exc.value.benchmark_cost_usd == pytest.approx(1200 / 1e6 * 3.0 + 400 / 1e6 * 15.0)


def test_the_truth_pass_reads_its_own_models_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    calls: list[str] = []
    monkeypatch.setattr(rb, "find_card", lambda manifest, card_id: {"card_id": card_id})
    monkeypatch.setattr(rb, "asset_path_for", lambda card: pdf)
    monkeypatch.setattr(rb, "rasterize_first_n", lambda path, n: ["img"])
    monkeypatch.setattr(rb, "run_engine_simple", lambda images, fn: [])
    monkeypatch.setattr(rb, "_summarize_rows", lambda *a, **k: None)
    monkeypatch.setattr(rb, "ADDENDUM_CANDIDATES", ())

    def fake_candidate(images, candidate, cache_root=None, budget=None):
        calls.append(candidate.model)
        return []

    monkeypatch.setattr(rb, "run_llm_candidate", fake_candidate)
    truth = rb.candidate_for_model("claude-sonnet-4-6")
    entry = {"category": "c", "description": "d"}
    rb.benchmark_card("abc", entry, None, truth, rb.Budget())
    assert calls == ["claude-sonnet-4-6"]

