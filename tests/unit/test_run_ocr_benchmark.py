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

import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

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
