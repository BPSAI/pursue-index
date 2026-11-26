"""One card's place in the coverage report: its route, tier and era."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pursue_index.file_basis import RowBasis
from pursue_index.provenance import ProvenanceTier

__all__ = ["CardOutcome", "outcome_of"]


@dataclass(frozen=True)
class CardOutcome:
    """One card's place in the coverage report: its route, tier and era."""

    card_id: str
    title: str
    agency: str
    era: str
    primary_tier: str | None
    resolved_by: str
    needs_page_image_comparison: bool
    row_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "row_key": self.row_key,
            "title": self.title,
            "agency": self.agency,
            "era": self.era,
            "primary_tier": self.primary_tier,
            "resolved_by": self.resolved_by,
            "needs_page_image_comparison": self.needs_page_image_comparison,
        }


def outcome_of(row: RowBasis) -> CardOutcome:
    """Place one reconciled, keyed row in exactly one route, as :func:`assess` routed it."""
    card_era, primary = row.era, (row.claim.tier if row.claim is not None else None)
    return CardOutcome(
        card_id=card_era.card_id,
        title=card_era.title,
        agency=card_era.agency,
        era=card_era.era.value,
        primary_tier=primary.value if primary is not None else None,
        resolved_by=row.route.value,
        needs_page_image_comparison=primary is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
        row_key=card_era.row_key,
    )
