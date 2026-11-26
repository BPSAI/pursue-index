"""Row and file routes shared by the era bucketing and the coverage report."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from pursue_index.era_models import Era

__all__ = ["Route", "file_route", "partially_resolved_files", "row_route"]


class Route(Enum):
    """Where a row or a file lands: resolved by a claim, by its era, or left unresolved."""

    CLAIM = "claim"
    ERA = "era"
    UNRESOLVED = "unresolved"


def row_route(has_claim: bool, era: Era, conflicted: bool) -> Route:
    """The one precedence for a row: a claim, else (no conflict and a modern era), else unresolved."""
    if has_claim:
        return Route.CLAIM
    if not conflicted and era is Era.MODERN_OPERATIONAL:
        return Route.ERA
    return Route.UNRESOLVED


def file_route(routes: Sequence[Route]) -> Route:
    """The mixed-outcome partition: any claim, else all era, else unresolved."""
    if Route.CLAIM in routes:
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
