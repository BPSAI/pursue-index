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
by ``unresolved_row_count``. A file has one era, and its route is the mixed-outcome
partition of :mod:`pursue_index.file_basis`: ``claim`` if any row has a claim, ``era`` if
every row routes ``era``, else ``unresolved``, with ``partially_resolved_files`` naming
the unresolved files that still have an era row. Pure computation + (de)serialisation over an
already-loaded manifest; the CLI (:mod:`pursue_index.cli.provenance_cli`) owns
all rendering and the read-only guard. No web payload is ever touched.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pursue_index.card_outcome import CardOutcome, outcome_of
from pursue_index.catalogue_load import LoadedCatalogue, load_catalogue
from pursue_index.claim_precedence import (
    POSITIVE_TIER_PRECEDENCE,
    claim_applies,
    unkeyed_claims,
)
from pursue_index.era_bucketing import classify_reconciled, classify_rows
from pursue_index.era_reconcile import FileEras
from pursue_index.file_basis import (
    Route,
    assess,
    file_routes,
    partially_resolved_files,
)
from pursue_index.file_counts import file_eras, file_key
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
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
_CLAIM_INHERITED = "claim_inherited"
RESOLVED_BY_ERA = "era"
UNRESOLVED = "unresolved"

def classify(
    card: dict[str, Any],
    catalogue: Sequence[SourceEntry] = (),
    external: Sequence[ResolvedClaim] = (),
    *,
    row_key: str,
    manifest: dict[str, Any] | None = None,
    report: CoverageReport | None = None,
) -> CardOutcome:
    """Resolve one card through the chain and place it in exactly one route.

    ``row_key`` is the row's real key in its manifest; a claim resolves only the
    row it names, so the key is never assumed. A row's route depends on its file: its
    siblings reconcile its era and lend it a claim. Pass the ``manifest`` the row
    belongs to and the result is that row's outcome in :func:`build_report`, whatever
    its siblings. Without it the card is taken as the only row of its file, and the
    result is only that row's outcome when the file has no other row.

    With a ``manifest``, ``card`` must be the manifest row ``row_key`` names, else
    ``ValueError``. Building the report is the cost of a call, so a caller classifying
    many rows passes the ``report`` it built once from that manifest; it is then not
    rebuilt, and its own catalogue and claims are the ones used. Passing ``catalogue``
    or ``external`` together with ``report`` is ambiguous and raises ``ValueError``.

    A ``report`` is stamped with the ``csv_sha256`` of the manifest it was built from and
    is refused (``ValueError``) when the stamp differs from the ``manifest`` passed, or
    when its length differs; a ``report`` without a ``manifest`` is refused too.

    The card-equality check runs only with a ``manifest``: the single-card path has no
    manifest row to compare the card with, since the card the caller passes is the only
    source of the row, so it cannot be checked, only taken as the file's only row.
    """
    if report is not None and (catalogue or external):
        raise ValueError("report carries its own catalogue and claims; do not pass catalogue or external with it")
    if report is not None and manifest is None:
        raise ValueError("a report is checked against the manifest it was built from; pass the manifest")
    if manifest is not None:
        built = report if report is not None else build_report(manifest, catalogue, external)
        cards = manifest.get("cards", [])
        if built.csv_sha256 != manifest.get("csv_sha256"):
            raise ValueError("the report was built from another csv_sha256 than this manifest")
        if len(built.outcomes) != len(cards):
            raise ValueError("the report was not built from this manifest")
        for outcome, row in zip(built.outcomes, cards, strict=True):
            if outcome.row_key == row_key:
                if row != card:
                    raise ValueError(f"card is not the manifest row {row_key!r}")
                return outcome
        raise KeyError(f"row_key {row_key!r} is not a row of the manifest")
    card_era = replace(classify_rows([card])[0], row_key=row_key)
    (row,) = assess([card], FileEras([card_era], {}), catalogue, external)
    return outcome_of(row)


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
    unkeyed_claim_count: int = 0
    unresolved_files: tuple[str, ...] = ()
    page_image_flagged_files: tuple[str, ...] = ()
    ntrs_claims_applied_row_count: int = 0
    csv_sha256: str | None = None
    partially_resolved_files: tuple[str, ...] = ()
    resolved_by_claim_inherited: int = 0

    def unresolved_rows(self) -> list[CardOutcome]:
        """The rows no route resolved — what Phase B would have to reach."""
        return [o for o in self.outcomes if o.resolved_by == UNRESOLVED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "csv_sha256": self.csv_sha256,
            "card_row_count": self.card_row_count,
            "file_count": self.file_count,
            "row_counts": self.row_counts,
            "unkeyed_claim_count": self.unkeyed_claim_count,
            "resolved_by_claim": self.resolved_by_claim,
            "resolved_by_era": self.resolved_by_era,
            "resolved_by_claim_inherited": self.resolved_by_claim_inherited,
            "unresolved": self.unresolved,
            "unresolved_files": list(self.unresolved_files),
            "partially_resolved_file_count": len(self.partially_resolved_files),
            "partially_resolved_files": list(self.partially_resolved_files),
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


_ROUTE_RANK = {RESOLVED_BY_CLAIM: 0, _CLAIM_INHERITED: 1, RESOLVED_BY_ERA: 2, UNRESOLVED: 3}


def _rank(outcome: CardOutcome) -> tuple[int, int]:
    """Order a file's rows: the strongest route, then the strongest tier, represents the file."""
    tiers = [t.value for t in POSITIVE_TIER_PRECEDENCE]
    tier = tiers.index(outcome.primary_tier) if outcome.primary_tier in tiers else len(tiers)
    return _ROUTE_RANK[outcome.resolved_by], tier


def _ntrs_rows_reached(claims: Sequence[ResolvedClaim], eras: Sequence[Any]) -> int:
    """Manifest rows an NTRS-sourced claim applies to, by the join ``positive_claims`` uses."""
    ntrs = [c for c in claims if c.source is ResolutionSource.NTRS_METADATA]
    return sum(1 for era in eras if any(claim_applies(c, file_key(era), era.row_key) for c in ntrs))


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

    A file (rows sharing a ``card_id``) is counted once, by the mixed-outcome partition:
    ``claim`` if any row has a claim, ``era`` if every row routes ``era``, else
    ``unresolved`` (``partially_resolved_files`` lists those with an era row).
    ``row_counts`` keeps the per-row split. A file is page-image-flagged when any of
    its rows is. A claim that names no row resolves nothing and is counted in
    ``unkeyed_claim_count``.

    ``extra_claims`` are positive claims from any further source (e.g. the NTRS
    metadata search); one resolves its card in the ``claim`` route like any other positive claim.
    """
    loaded = catalogue if isinstance(catalogue, LoadedCatalogue) else LoadedCatalogue(list(catalogue), 0)
    cards = manifest.get("cards", [])
    reconciled = classify_reconciled(cards)
    rows = assess(cards, reconciled, loaded.entries, extra_claims)
    eras = reconciled.cards
    outcomes = [outcome_of(row) for row in rows]
    row_routes = Counter(o.resolved_by for o in outcomes)
    routes = file_routes(rows)
    file_era = file_eras(eras, reconciled.conflicts)
    best: dict[str, CardOutcome] = {}
    flagged: dict[str, None] = {}
    for era, outcome in zip(eras, outcomes, strict=True):
        key = file_key(era)
        if outcome.needs_page_image_comparison:
            flagged[key] = None
        if key not in best or _rank(outcome) < _rank(best[key]):
            best[key] = outcome
    by_route = Counter(route.value for route in routes.values())
    tier_counts = Counter(best[k].primary_tier for k, r in routes.items() if r is Route.CLAIM and best[k].primary_tier)
    unresolved_files = tuple(k for k, r in routes.items() if r is Route.UNRESOLVED)
    unresolved_by_era = Counter(file_era[k] for k in unresolved_files)
    return CoverageReport(
        card_row_count=len(outcomes),
        resolved_by_claim=by_route[RESOLVED_BY_CLAIM],
        resolved_by_era=by_route[RESOLVED_BY_ERA],
        unresolved=by_route[UNRESOLVED],
        tier_counts={t.value: tier_counts[t.value] for t in POSITIVE_TIER_PRECEDENCE if tier_counts[t.value]},
        page_image_flagged=len(flagged),
        unresolved_by_era=dict(sorted(unresolved_by_era.items())),
        outcomes=tuple(outcomes),
        catalogue_entries=len(loaded.entries),
        catalogue_rows_dropped=loaded.dropped_rows,
        file_count=len(routes),
        row_counts={route: row_routes[route] for route in (RESOLVED_BY_CLAIM, _CLAIM_INHERITED, RESOLVED_BY_ERA, UNRESOLVED)},
        resolved_by_claim_inherited=row_routes[_CLAIM_INHERITED],
        unkeyed_claim_count=unkeyed_claims(extra_claims),
        unresolved_files=unresolved_files,
        page_image_flagged_files=tuple(flagged),
        ntrs_claims_applied_row_count=_ntrs_rows_reached(extra_claims, eras),
        csv_sha256=manifest.get("csv_sha256"),
        partially_resolved_files=tuple(
            partially_resolved_files([row.route for row in rows], [file_key(row.era) for row in rows])
        ),
    )
