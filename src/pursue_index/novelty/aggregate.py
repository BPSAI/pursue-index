"""Aggregate per-page top-1 similarity scores into card-level disclosure status.

Rules (defaults from the novelty-detection plan):
- ``previously-disclosed`` — >70% of pages score >= 0.85 against any reference.
- ``novel`` — >70% of pages score < 0.70 against any reference.
- ``partial`` — anything else (mixed signals).

``novelty_score`` is ``1 - mean(top-1 similarity)`` so card lists can
sort highest-novelty-first without the UI flipping the sign.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pursue_index.novelty.compare import PageMatch

DisclosureStatus = Literal["novel", "partial", "previously-disclosed"]


@dataclass(frozen=True)
class Thresholds:
    """Cutoffs for the page-level similarity → status decision.

    ``high`` is the "previously disclosed" floor; ``partial`` is the "still
    novel" ceiling. Pages between the two are partial overlaps.
    """

    high: float = 0.85
    partial: float = 0.70


DEFAULT_THRESHOLDS = Thresholds()
NOVEL_FRACTION = 0.70  # >70% of pages must be on one side to commit to novel/disclosed


@dataclass(frozen=True)
class CardNovelty:
    """Per-card novelty record written into the sidecar JSON."""

    card_id: str
    disclosure_status: DisclosureStatus
    novelty_score: float
    top_matches: list[PageMatch]


def _classify(scores: list[float], thresholds: Thresholds) -> DisclosureStatus:
    """Decide ``novel`` / ``partial`` / ``previously-disclosed`` from a scores list."""
    if not scores:
        return "novel"
    n = len(scores)
    high_count = sum(1 for s in scores if s >= thresholds.high)
    low_count = sum(1 for s in scores if s < thresholds.partial)
    if high_count / n > NOVEL_FRACTION:
        return "previously-disclosed"
    if low_count / n > NOVEL_FRACTION:
        return "novel"
    return "partial"


def aggregate_card(
    card_id: str,
    matches: list[PageMatch],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> CardNovelty:
    """Roll a list of per-page matches up to a single card-level verdict."""
    if not matches:
        return CardNovelty(
            card_id=card_id,
            disclosure_status="novel",
            novelty_score=1.0,
            top_matches=[],
        )
    scores = [m.similarity for m in matches]
    status = _classify(scores, thresholds)
    novelty_score = 1.0 - (sum(scores) / len(scores))
    top = sorted(matches, key=lambda m: m.similarity, reverse=True)[:3]
    return CardNovelty(
        card_id=card_id,
        disclosure_status=status,
        novelty_score=round(max(0.0, min(1.0, novelty_score)), 4),
        top_matches=top,
    )
