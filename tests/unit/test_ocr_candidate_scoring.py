"""Addendum candidates are scored against the same truth proxy as the others."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_ocr_report  # type: ignore[import-not-found] # noqa: E402
from _ocr_metrics import (  # type: ignore[import-not-found] # noqa: E402
    compute_candidate_metrics,
    compute_metrics,
)


def _row(text: str, cost: float = 0.0) -> dict:
    return {"page": 1, "text": text, "confidence": 90.0, "wall_clock_s": 1.0,
            "cost_usd": cost, "tokens": {}}


def _card(candidate_text: str) -> dict:
    return {"engines": {
        "tesseract": [_row("the quick brown fox")], "surya": [_row("the quick brown fox")],
        "llm": [_row("the quick brown fox")],
        "llm_candidates": {"cand": [_row(candidate_text, 0.5)]},
    }}


def test_an_accurate_candidate_scores_zero_error() -> None:
    agg = compute_candidate_metrics([_card("the quick brown fox")])
    assert agg["cand"]["cer_list"] == [0.0] and agg["cand"]["wer_list"] == [0.0]


def test_a_wrong_candidate_is_distinguishable_from_an_accurate_one() -> None:
    right = compute_candidate_metrics([_card("the quick brown fox")])["cand"]
    wrong = compute_candidate_metrics([_card("zzzz qqqq")])["cand"]
    assert wrong["cer_list"][0] > right["cer_list"][0]
    assert wrong["wer_list"][0] > right["wer_list"][0]


def test_report_prints_candidate_error_columns() -> None:
    cards = [_card("zzzz qqqq")]
    table = build_ocr_report.render_summary_table(
        compute_metrics(cards), [], None, compute_candidate_metrics(cards),
    )
    line = next(ln for ln in table.splitlines() if "LLM candidate (cand)" in ln)
    assert "—" not in line.split("|")[4]  # median CER column is a number
