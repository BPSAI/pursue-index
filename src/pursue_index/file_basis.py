"""Row and file routes, shared by the era bucketing and the coverage report.

A row routes to ``claim`` (it has a positive claim of its own, whether or not its
file's dated rows conflict), else to ``claim_inherited`` (another row of its file has
one), else to ``era`` (a non-conflict file whose era is 2015+), else is ``unresolved``. A file routes by the mixed-outcome partition: ``claim`` if any row has
a claim (a claim is about the document, and every row is that document), ``era`` if
no row has a claim and every row routes ``era``, else ``unresolved``. The file counts
partition ``file_count``, the row counts partition ``card_row_count``, and an
unresolved file that still has an era row is listed as partially resolved, so no
unresolved row is hidden behind a stronger sibling.

A positive claim is about the document, so inheritance is file-level: a row without a
claim of its own takes the strongest claim of any row in its file (by tier precedence,
the lowest ``row_key`` winning a tie), conflict files included, and no row of a claimed
file emits a negative. ``claim_inherited`` is a row route only: a file is ``claim``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pursue_index.claim_precedence import (
    POSITIVE_TIER_PRECEDENCE,
    PositiveClaim,
    primary_positive_claim,
)
from pursue_index.era_models import CardEra, Era
from pursue_index.era_reconcile import FileEras
from pursue_index.file_counts import file_key
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.row_key import row_index
from pursue_index.source_index import SourceEntry

__all__ = [
    "Route",
    "RowBasis",
    "assess",
    "file_route",
    "file_routes",
    "partially_resolved_files",
    "route_fields",
    "row_route",
]


class Route(Enum):
    """Where a row or a file lands: resolved by a claim, by its era, or left unresolved."""

    CLAIM = "claim"
    CLAIM_INHERITED = "claim_inherited"
    ERA = "era"
    UNRESOLVED = "unresolved"


def row_route(has_claim: bool, era: Era, conflicted: bool, inherited: bool = False) -> Route:
    """The one precedence for a row: its own claim, an inherited one, a modern era, else unresolved."""
    if has_claim:
        return Route.CLAIM
    if inherited:
        return Route.CLAIM_INHERITED
    if not conflicted and era is Era.MODERN_OPERATIONAL:
        return Route.ERA
    return Route.UNRESOLVED


def file_route(routes: Sequence[Route]) -> Route:
    """The mixed-outcome partition: any claim, else all era, else unresolved."""
    if Route.CLAIM in routes or Route.CLAIM_INHERITED in routes:
        return Route.CLAIM
    if routes and all(route is Route.ERA for route in routes):
        return Route.ERA
    return Route.UNRESOLVED


def partially_resolved_files(routes: Sequence[Route], file_keys: Sequence[str]) -> list[str]:
    """Unresolved files with at least one era row, in first-seen order."""
    by_file: dict[str, list[Route]] = {}
    for key, route in zip(file_keys, routes, strict=True):
        by_file.setdefault(key, []).append(route)
    return [
        key
        for key, rows in by_file.items()
        if file_route(rows) is Route.UNRESOLVED and Route.ERA in rows
    ]


@dataclass(frozen=True)
class RowBasis:
    """One reconciled row with its claim (own or inherited), conflict reason and route."""

    era: CardEra
    claim: PositiveClaim | None
    conflict: str | None
    route: Route
    inherited_from: str | None = None


def _strongest(claims: list[tuple[str, PositiveClaim]]) -> tuple[str, PositiveClaim] | None:
    """The strongest claim by tier precedence; the lowest row index (numeric) wins a tie."""
    for tier in POSITIVE_TIER_PRECEDENCE:
        for entry in sorted(claims, key=lambda item: (row_index(item[0]), item[0])):
            if entry[1].tier is tier:
                return entry
    return None


def _effective_claims(
    cards: Sequence[dict[str, Any]],
    eras: Sequence[CardEra],
    catalogue: Sequence[SourceEntry],
    external: Sequence[ResolvedClaim],
) -> list[tuple[PositiveClaim | None, str | None]]:
    """Each row's claim and, if inherited, the row it came from; inheritance is file-level.

    A conflicted row inherits like any other: the claim is about the file.
    """
    own = [
        primary_positive_claim(card, catalogue, external, row_key=era.row_key)
        for card, era in zip(cards, eras, strict=True)
    ]
    by_file: dict[str, list[tuple[str, PositiveClaim]]] = {}
    for era, claim in zip(eras, own, strict=True):
        if claim is not None:
            by_file.setdefault(file_key(era), []).append((era.row_key, claim))
    effective: list[tuple[PositiveClaim | None, str | None]] = []
    for era, claim in zip(eras, own, strict=True):
        if claim is not None:
            effective.append((claim, None))
            continue
        source = _strongest(by_file.get(file_key(era), []))
        effective.append((source[1], source[0]) if source else (None, None))
    return effective


def assess(
    cards: Sequence[dict[str, Any]],
    reconciled: FileEras,
    catalogue: Sequence[SourceEntry] = (),
    external: Sequence[ResolvedClaim] = (),
) -> list[RowBasis]:
    """Route every reconciled row, once; the bucketing and the report both read this."""
    eras = reconciled.cards
    claims = _effective_claims(cards, eras, catalogue, external)
    rows: list[RowBasis] = []
    for era, (claim, source) in zip(eras, claims, strict=True):
        conflict = reconciled.conflicts.get(era.row_key)
        route = row_route(claim is not None and source is None, era.era, conflict is not None, source is not None)
        rows.append(RowBasis(era, claim, conflict, route, source))
    return rows


def file_routes(rows: Sequence[RowBasis]) -> dict[str, Route]:
    """One route per file, in first-seen order."""
    by_file: dict[str, list[Route]] = {}
    for row in rows:
        by_file.setdefault(file_key(row.era), []).append(row.route)
    return {key: file_route(routes) for key, routes in by_file.items()}


def route_fields(rows: Sequence[RowBasis]) -> dict[str, Any]:
    """The partition counts: per file, per row, and the partially resolved files."""
    per_file = Counter(file_routes(rows).values())
    file_partition = (Route.CLAIM, Route.ERA, Route.UNRESOLVED)
    per_row = Counter(row.route for row in rows)
    return {
        "file_route_counts": {route.value: per_file[route] for route in file_partition},
        "row_route_counts": {route.value: per_row[route] for route in Route},
        "partially_resolved_files": partially_resolved_files(
            [row.route for row in rows], [file_key(row.era) for row in rows]
        ),
    }
