"""Provenance coverage report over the full resolution chain (spec §5).

Phase A resolves the corpus with three stages: the Tier-0 sweep of the
government's own descriptions, era bucketing, and the identifier
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
page-image comparison.

Units. ``row_key`` (``<card_id>#<n>``) is the per-row key; ``card_id`` names a source
file and is not unique upstream, since several rows can share one. A count named
``*_row_count`` (or ``row_counts``) counts rows and equals the length of the row array
beside it. Every other count is per file: ``unresolved`` is the length of
``unresolved_files`` (one id per file), and ``unresolved_rows`` lists the rows, counted
by ``unresolved_row_count``. A file whose rows land in different eras is counted
once under ``mixed``. Pure computation + (de)serialisation over an
already-loaded manifest; the CLI (:mod:`pursue_index.cli.provenance_cli`) owns
all rendering and the read-only guard. No web payload is ever touched.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.claim_precedence import (
    POSITIVE_TIER_PRECEDENCE,
    PositiveClaim,
    primary_positive_claim,
    unkeyed_claims,
)
from pursue_index.era_bucketing import classify_rows
from pursue_index.era_models import CardEra, Era
from pursue_index.file_counts import file_eras, file_key
from pursue_index.provenance import ProvenanceTier
from pursue_index.resolved_claim import ResolvedClaim
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


def classify(
    card: dict[str, Any],
    catalogue: Sequence[SourceEntry] = (),
    external: Sequence[ResolvedClaim] = (),
    *,
    row_key: str,
) -> CardOutcome:
    """Resolve one card through the chain and place it in exactly one route.

    ``row_key`` is the row's real key in its manifest; a claim resolves only the
    row it names, so the key is never assumed.
    """
    card_era = replace(classify_rows([card])[0], row_key=row_key)
    return _outcome(card_era, primary_positive_claim(card, catalogue, external, row_key=row_key))


def _outcome(card_era: CardEra, claim: PositiveClaim | None) -> CardOutcome:
    """Place one keyed row in exactly one route, given its strongest claim."""
    primary = claim.tier if claim is not None else None
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
        row_key=card_era.row_key,
    )


_SCHEMA = "provenance-coverage-report/v2"


@dataclass(frozen=True)
class CoverageReport:
    """The Phase-A coverage answer: the three routes, per-tier and per-era.

    ``card_row_count`` is manifest rows. The route counts, ``tier_counts``,
    ``page_image_flagged`` and ``unresolved_by_era`` are per source file (see
    :func:`build_report`); ``row_counts`` is the same route split per row, and
    ``outcomes`` stays one entry per row. ``unresolved_files`` names the files
    ``unresolved`` counts.
    """

    card_row_count: int
    resolved_by_claim: int
    resolved_by_era: int
    unresolved: int
    tier_counts: dict[str, int]
    page_image_flagged: int
    unresolved_by_era: dict[str, int]
    outcomes: tuple[CardOutcome, ...]
    catalogue_entries: int = 0
    catalogue_rows_dropped: int = 0
    file_count: int = 0
    row_counts: dict[str, int] = field(default_factory=dict)
    claims_without_row_key: int = 0
    unresolved_files: tuple[str, ...] = ()
    page_image_flagged_files: tuple[str, ...] = ()
    ntrs_claims_applied_row_count: int = 0

    def unresolved_rows(self) -> list[CardOutcome]:
        """The rows no route resolved — what Phase B would have to reach."""
        return [o for o in self.outcomes if o.resolved_by == UNRESOLVED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "card_row_count": self.card_row_count,
            "file_count": self.file_count,
            "row_counts": self.row_counts,
            "claims_without_row_key": self.claims_without_row_key,
            "resolved_by_claim": self.resolved_by_claim,
            "resolved_by_era": self.resolved_by_era,
            "unresolved": self.unresolved,
            "unresolved_files": list(self.unresolved_files),
            "tier_file_counts": self.tier_counts,
            "page_image_flagged": self.page_image_flagged,
            "unresolved_by_era": self.unresolved_by_era,
            "catalogue_entries": self.catalogue_entries,
            "catalogue_rows_dropped": {
                "count": self.catalogue_rows_dropped,
                "reason": INVALID_URL_EXCLUSION_REASON,
            },
            "page_image_flagged_files": list(self.page_image_flagged_files),
            "ntrs_claims_applied_row_count": self.ntrs_claims_applied_row_count,
            "unresolved_row_count": len(self.unresolved_rows()),
            "unresolved_rows": [o.to_dict() for o in self.unresolved_rows()],
        }


_ROUTE_RANK = {RESOLVED_BY_CLAIM: 0, RESOLVED_BY_ERA: 1, UNRESOLVED: 2}


def _rank(outcome: CardOutcome) -> tuple[int, int]:
    """Order a file's rows: the strongest route, then the strongest tier, represents the file."""
    tiers = [t.value for t in POSITIVE_TIER_PRECEDENCE]
    tier = tiers.index(outcome.primary_tier) if outcome.primary_tier in tiers else len(tiers)
    return _ROUTE_RANK[outcome.resolved_by], tier


def build_report(
    manifest: dict[str, Any],
    catalogue: Sequence[SourceEntry] | LoadedCatalogue = (),
    extra_claims: Sequence[ResolvedClaim] = (),
) -> CoverageReport:
    """Run the chain over every card and aggregate the coverage split.

    ``catalogue`` may be a plain sequence of entries or a
    :class:`~pursue_index.catalogue_load.LoadedCatalogue`. The loaded form also
    carries how many stored rows could not be read, and the report publishes
    that: a coverage figure is a statement about how much was searched, so the
    part of the catalogue that was unreadable belongs in it.

    A file (rows sharing a ``card_id``) is counted once: it takes the strongest
    route any of its rows has (claim, then era, then unresolved), and a file whose
    rows land in different eras is counted ``mixed``. ``row_counts`` keeps the
    per-row split. A file is page-image-flagged when any of its rows is. A claim that names no row resolves nothing and is counted in
    ``claims_without_row_key``.

    ``extra_claims`` are positive claims from any further source (e.g. the NTRS
    metadata search); one resolves its card in the ``claim`` route like any other positive claim.
    """
    loaded = catalogue if isinstance(catalogue, LoadedCatalogue) else LoadedCatalogue(list(catalogue), 0)
    cards = manifest.get("cards", [])
    eras = classify_rows(cards)
    outcomes = [
        _outcome(era, primary_positive_claim(card, loaded.entries, extra_claims, row_key=era.row_key))
        for card, era in zip(cards, eras, strict=True)
    ]
    row_routes = Counter(o.resolved_by for o in outcomes)
    file_era = file_eras(eras)
    best: dict[str, CardOutcome] = {}
    flagged: dict[str, None] = {}
    for era, outcome in zip(eras, outcomes, strict=True):
        key = file_key(era)
        if outcome.needs_page_image_comparison:
            flagged[key] = None
        if key not in best or _rank(outcome) < _rank(best[key]):
            best[key] = outcome
    routes = Counter(o.resolved_by for o in best.values())
    tier_counts = Counter(o.primary_tier for o in best.values() if o.primary_tier is not None)
    unresolved_by_era = Counter(file_era[k] for k, o in best.items() if o.resolved_by == UNRESOLVED)
    return CoverageReport(
        card_row_count=len(outcomes),
        resolved_by_claim=routes[RESOLVED_BY_CLAIM],
        resolved_by_era=routes[RESOLVED_BY_ERA],
        unresolved=routes[UNRESOLVED],
        tier_counts={t.value: tier_counts[t.value] for t in POSITIVE_TIER_PRECEDENCE if tier_counts[t.value]},
        page_image_flagged=len(flagged),
        unresolved_by_era=dict(sorted(unresolved_by_era.items())),
        outcomes=tuple(outcomes),
        catalogue_entries=len(loaded.entries),
        catalogue_rows_dropped=loaded.dropped_rows,
        file_count=len(best),
        row_counts={route: row_routes[route] for route in (RESOLVED_BY_CLAIM, RESOLVED_BY_ERA, UNRESOLVED)},
        claims_without_row_key=unkeyed_claims(extra_claims),
        unresolved_files=tuple(k for k, o in best.items() if o.resolved_by == UNRESOLVED),
        page_image_flagged_files=tuple(flagged),
        ntrs_claims_applied_row_count=sum(1 for claim in extra_claims if claim.row_key),
    )
