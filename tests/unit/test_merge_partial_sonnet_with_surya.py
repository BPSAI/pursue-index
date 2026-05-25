"""Unit tests for the partial-Sonnet + Surya merge helper.

The merge is a per-page preference: when Sonnet has a row for a given
page (because it OCR'd that page before hitting Anthropic's content
filter), use it; otherwise fall back to the Surya row from a follow-up
full-card re-OCR.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))

from merge_partial_sonnet_with_surya import merge_rows  # noqa: E402


def _row(page: int, engine: str) -> dict:
    return {"page": page, "text": f"{engine}-page-{page}", "confidence": 90.0, "engine": engine}


def test_merge_prefers_sonnet_where_present() -> None:
    """Sonnet rows win for any page they cover."""
    sonnet = [_row(1, "llm"), _row(2, "llm"), _row(3, "llm")]
    surya = [_row(1, "surya"), _row(2, "surya"), _row(3, "surya"), _row(4, "surya")]
    merged = merge_rows(sonnet, surya)
    # First 3 should be llm (Sonnet), 4th surya
    assert [r["engine"] for r in merged] == ["llm", "llm", "llm", "surya"]
    # Verify text origin preserved (not contaminated from the other source)
    assert merged[0]["text"] == "llm-page-1"
    assert merged[3]["text"] == "surya-page-4"


def test_merge_keeps_surya_when_sonnet_empty() -> None:
    """Empty Sonnet partial → all Surya rows preserved as-is."""
    surya = [_row(1, "surya"), _row(2, "surya")]
    merged = merge_rows([], surya)
    assert merged == surya


def test_merge_preserves_surya_page_ordering() -> None:
    """Output is ordered by the Surya page sequence — never page-skipped."""
    sonnet = [_row(5, "llm"), _row(1, "llm")]  # out-of-order partial
    surya = [_row(i, "surya") for i in range(1, 7)]
    merged = merge_rows(sonnet, surya)
    pages = [r["page"] for r in merged]
    assert pages == [1, 2, 3, 4, 5, 6]
    # Sonnet wins at the pages it covers
    assert merged[0]["engine"] == "llm"  # page 1
    assert merged[4]["engine"] == "llm"  # page 5
    # Surya elsewhere
    assert merged[1]["engine"] == "surya"
    assert merged[5]["engine"] == "surya"


def test_merge_does_not_drop_or_duplicate() -> None:
    """Every Surya page appears exactly once in the merged output."""
    sonnet = [_row(2, "llm"), _row(4, "llm")]
    surya = [_row(i, "surya") for i in range(1, 6)]
    merged = merge_rows(sonnet, surya)
    assert len(merged) == 5
    assert sorted(r["page"] for r in merged) == [1, 2, 3, 4, 5]
