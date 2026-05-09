"""Tests for the page→card novelty aggregation.

The rule: a card is ``novel`` if >70% of pages score below the partial
threshold (default 0.70); ``previously-disclosed`` if >70% of pages
score at or above the high threshold (default 0.85); ``partial``
otherwise. The novelty_score is 1 - mean(top-1 similarities) so a
high-novelty card sorts higher.
"""

from __future__ import annotations

from pursue_index.novelty.aggregate import (
    DEFAULT_THRESHOLDS,
    Thresholds,
    aggregate_card,
)
from pursue_index.novelty.compare import PageMatch


def _matches(scores: list[float]) -> list[PageMatch]:
    return [
        PageMatch(
            page=i + 1,
            ref_card_id=f"ref-{i}",
            ref_page=1,
            similarity=s,
            archive_id="synthetic",
        )
        for i, s in enumerate(scores)
    ]


def test_aggregate_card_marks_all_low_scores_novel():
    """All 5 pages score 0.20 → well below partial threshold → novel."""
    matches = _matches([0.2, 0.2, 0.2, 0.2, 0.2])
    result = aggregate_card("card-A", matches, DEFAULT_THRESHOLDS)
    assert result.disclosure_status == "novel"
    assert result.novelty_score > 0.7


def test_aggregate_card_marks_all_high_scores_previously_disclosed():
    """All 5 pages score 0.95 → above high threshold → previously-disclosed."""
    matches = _matches([0.95, 0.95, 0.95, 0.95, 0.95])
    result = aggregate_card("card-B", matches, DEFAULT_THRESHOLDS)
    assert result.disclosure_status == "previously-disclosed"
    assert result.novelty_score < 0.1


def test_aggregate_card_marks_mixed_scores_partial():
    """3 high (0.92) + 2 low (0.30) → 60/40 split → partial."""
    matches = _matches([0.92, 0.92, 0.92, 0.30, 0.30])
    result = aggregate_card("card-C", matches, DEFAULT_THRESHOLDS)
    assert result.disclosure_status == "partial"


def test_aggregate_card_just_over_70_percent_novel():
    """8/10 pages below partial threshold (>70%) → still novel."""
    matches = _matches([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.9, 0.9])
    result = aggregate_card("card-D", matches, DEFAULT_THRESHOLDS)
    assert result.disclosure_status == "novel"


def test_aggregate_card_with_no_matches_is_novel():
    """An empty match list (no reference at all) is novel by definition."""
    result = aggregate_card("card-E", [], DEFAULT_THRESHOLDS)
    assert result.disclosure_status == "novel"
    assert result.novelty_score == 1.0


def test_aggregate_card_custom_thresholds():
    """Custom thresholds shift the boundaries — verify the knob works."""
    strict = Thresholds(high=0.95, partial=0.85)
    # 0.90 sims would be "previously-disclosed" at default but only "partial" at strict.
    matches = _matches([0.90, 0.90, 0.90, 0.90, 0.90])
    result = aggregate_card("card-F", matches, strict)
    assert result.disclosure_status == "partial"


def test_aggregate_card_carries_top3_matches():
    """The aggregator preserves the top-3 highest-similarity matches for UI display."""
    matches = _matches([0.10, 0.50, 0.90, 0.80, 0.20])
    result = aggregate_card("card-G", matches, DEFAULT_THRESHOLDS)
    assert len(result.top_matches) == 3
    sims = [m.similarity for m in result.top_matches]
    assert sims == sorted(sims, reverse=True)
    assert sims[0] == 0.90
