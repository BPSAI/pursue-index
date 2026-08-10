"""Provenance coverage report over the full resolution chain (spec §5, PV1.6).

Phase A resolves the corpus with three stages: PV1.2's Tier-0 sweep of the
government's own descriptions, PV1.3's era bucketing, and PV1.5's identifier
resolver. This module runs all three over a manifest and reports *coverage* —
how many of the cards each route resolved — so the `/methodology` exit
condition can be judged: did Phase A answer enough of the corpus, or is the
page-image phase (Phase B) genuinely required?

The report holds one line the doctrine insists on: a card resolved by a
positive **prior-release claim** is never conflated with a card resolved by
**era alone**. Each card is placed in exactly one route:

* ``claim`` — carries a positive claim (``previously_released``,
  ``previously_released_in_part`` or ``content_previously_published``) from the
  Tier-0 sweep or the identifier resolver. A positive claim wins even when the
  card is also a 2015+ document.
* ``era`` — a 2015+ card with no positive claim: the era-based
  no-prior-release conclusion, counted on its own so it is never mistaken for a
  resolved prior release.
* ``unresolved`` — pre-2015 with no claim, or undated. These are the cards
  Phase B would have to reach.

Cards whose claim is ``previously_released_in_part`` are flagged for the later
page-image comparison. Pure computation + (de)serialisation over an
already-loaded manifest; the CLI (:mod:`pursue_index.cli.provenance_cli`) owns
all rendering and the read-only guard. No web payload is ever touched.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.claim_precedence import POSITIVE_TIER_PRECEDENCE, primary_positive_tier
from pursue_index.era_bucketing import classify_card
from pursue_index.era_models import Era
from pursue_index.provenance import ProvenanceTier
from pursue_index.source_index import INVALID_URL_EXCLUSION_REASON, SourceEntry

__all__ = [
    "POSITIVE_TIER_PRECEDENCE",
    "RESOLVED_BY_CLAIM",
    "RESOLVED_BY_ERA",
    "UNRESOLVED",
    "CardOutcome",
    "CoverageReport",
    "LoadedCatalogue",
    "build_report",
    "classify",
    "load_catalogue",
]

#: The route a card was resolved by. The first two are kept strictly apart —
#: an era conclusion is never counted as a resolved prior-release claim.
RESOLVED_BY_CLAIM = "claim"
RESOLVED_BY_ERA = "era"
UNRESOLVED = "unresolved"

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "agency": self.agency,
            "era": self.era,
            "primary_tier": self.primary_tier,
            "resolved_by": self.resolved_by,
            "needs_page_image_comparison": self.needs_page_image_comparison,
        }


def classify(card: dict[str, Any], catalogue: Sequence[SourceEntry] = ()) -> CardOutcome:
    """Resolve one card through the chain and place it in exactly one route."""
    primary = primary_positive_tier(card, catalogue)
    card_era = classify_card(card)
    if primary is not None:
        resolved_by = RESOLVED_BY_CLAIM
    elif card_era.era is Era.MODERN_OPERATIONAL:
        resolved_by = RESOLVED_BY_ERA
    else:
        resolved_by = UNRESOLVED
    return CardOutcome(
        card_id=card_era.card_id,
        title=card_era.title,
        agency=card_era.agency,
        era=card_era.era.value,
        primary_tier=primary.value if primary is not None else None,
        resolved_by=resolved_by,
        needs_page_image_comparison=primary is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
    )


@dataclass(frozen=True)
class CoverageReport:
    """The Phase-A coverage answer: the three routes, per-tier and per-era."""

    card_count: int
    resolved_by_claim: int
    resolved_by_era: int
    unresolved: int
    tier_counts: dict[str, int]
    page_image_flagged: int
    unresolved_by_era: dict[str, int]
    outcomes: tuple[CardOutcome, ...]
    catalogue_entries: int = 0
    catalogue_rows_dropped: int = 0

    def unresolved_cards(self) -> list[CardOutcome]:
        """The cards no route resolved — what Phase B would have to reach."""
        return [o for o in self.outcomes if o.resolved_by == UNRESOLVED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_count": self.card_count,
            "resolved_by_claim": self.resolved_by_claim,
            "resolved_by_era": self.resolved_by_era,
            "unresolved": self.unresolved,
            "tier_counts": self.tier_counts,
            "page_image_flagged": self.page_image_flagged,
            "unresolved_by_era": self.unresolved_by_era,
            "catalogue_entries": self.catalogue_entries,
            "catalogue_rows_dropped": {
                "count": self.catalogue_rows_dropped,
                "reason": INVALID_URL_EXCLUSION_REASON,
            },
            "unresolved_cards": [o.to_dict() for o in self.unresolved_cards()],
        }


def build_report(
    manifest: dict[str, Any],
    catalogue: Sequence[SourceEntry] | LoadedCatalogue = (),
) -> CoverageReport:
    """Run the chain over every card and aggregate the coverage split.

    ``catalogue`` may be a plain sequence of entries or a
    :class:`~pursue_index.catalogue_load.LoadedCatalogue`. The loaded form also
    carries how many stored rows could not be read, and the report publishes
    that: a coverage figure is a statement about how much was searched, so the
    part of the catalogue that was unreadable belongs in it.
    """
    loaded = catalogue if isinstance(catalogue, LoadedCatalogue) else LoadedCatalogue(list(catalogue), 0)
    outcomes = [classify(card, loaded.entries) for card in manifest.get("cards", [])]
    routes = Counter(o.resolved_by for o in outcomes)
    tier_counts = Counter(o.primary_tier for o in outcomes if o.primary_tier is not None)
    unresolved_by_era = Counter(o.era for o in outcomes if o.resolved_by == UNRESOLVED)
    return CoverageReport(
        card_count=len(outcomes),
        resolved_by_claim=routes[RESOLVED_BY_CLAIM],
        resolved_by_era=routes[RESOLVED_BY_ERA],
        unresolved=routes[UNRESOLVED],
        tier_counts={t.value: tier_counts[t.value] for t in POSITIVE_TIER_PRECEDENCE if tier_counts[t.value]},
        page_image_flagged=sum(1 for o in outcomes if o.needs_page_image_comparison),
        unresolved_by_era=dict(sorted(unresolved_by_era.items())),
        outcomes=tuple(outcomes),
        catalogue_entries=len(loaded.entries),
        catalogue_rows_dropped=loaded.dropped_rows,
    )
