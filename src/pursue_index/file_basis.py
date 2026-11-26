"""The source file is the unit of count; a reconciled row shares its file's status.

Rows sharing a ``card_id`` name one file, so a headline count is over files, not
rows. A file has one era once its rows are reconciled. A file whose rows still
carry more than one era (dated rows that disagree) has no single era, and is
counted once under ``undated``. A row with no ``card_id`` is a file of its own.

A reconciled row has no date of its own, only its dated sibling's, so it takes
that sibling's prior-release status too: a positive claim on the sibling is
evidence about the file, and a negative inferred from the same file's date must
not contradict it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from enum import Enum
from typing import Any

from pursue_index.claim_precedence import (
    POSITIVE_TIER_PRECEDENCE,
    PositiveClaim,
    primary_positive_claim,
    unkeyed_claims,
)
from pursue_index.era_models import CardEra, Era, EraNoPriorRelease
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.source_index import SourceEntry

__all__ = ["Route", "count_fields", "effective_claims", "file_eras", "file_key", "row_route", "tallies"]


class Route(Enum):
    """Where a row lands: resolved by a claim, by its era, or left unresolved."""

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


def file_key(card: CardEra) -> str:
    """The file a row belongs to: its ``card_id``, or its own key when it has none."""
    return card.card_id or card.row_key


def file_eras(cards: Sequence[CardEra], conflicts: Collection[str] = ()) -> dict[str, Era]:
    """One era per file; a file whose rows disagree, or conflict on year, is ``undated``."""
    seen: dict[str, set[Era]] = {}
    for card in cards:
        seen.setdefault(file_key(card), set()).add(card.era)
    conflicted = {file_key(card) for card in cards if card.row_key in conflicts}
    return {
        key: next(iter(eras)) if len(eras) == 1 and key not in conflicted else Era.UNDATED
        for key, eras in seen.items()
    }


def tallies(
    cards: Sequence[CardEra], conflicts: Collection[str] = ()
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Era counts per file and per row (every era present), and agency counts per row."""
    per_file = {era.value: 0 for era in Era}
    per_file.update(Counter(era.value for era in file_eras(cards, conflicts).values()))
    per_row = {era.value: 0 for era in Era}
    per_row.update(Counter(card.era.value for card in cards))
    return per_file, per_row, dict(sorted(Counter(card.agency for card in cards).items()))


def count_fields(
    cards: Sequence[CardEra],
    claims: Sequence[EraNoPriorRelease],
    external: Sequence[ResolvedClaim] = (),
    conflicts: Collection[str] = (),
) -> dict[str, Any]:
    """The count-bearing ``BucketResult`` fields: per file, per row, and unkeyed claims."""
    era_counts, era_row_counts, agency_row_counts = tallies(cards, conflicts)
    return {
        "era_counts": era_counts,
        "era_row_counts": era_row_counts,
        "file_count": sum(era_counts.values()),
        "no_prior_release_files": list(dict.fromkeys(claim.card_id for claim in claims)),
        "claims_without_row_key": unkeyed_claims(external),
        "agency_row_counts": agency_row_counts,
    }


def _strongest(claims: list[PositiveClaim]) -> PositiveClaim | None:
    for tier in POSITIVE_TIER_PRECEDENCE:
        for claim in claims:
            if claim.tier is tier:
                return claim
    return None


def effective_claims(
    cards: Sequence[dict[str, Any]],
    eras: Sequence[CardEra],
    catalogue: Sequence[SourceEntry] = (),
    external: Sequence[ResolvedClaim] = (),
) -> list[PositiveClaim | None]:
    """Each row's strongest positive claim; a reconciled row falls back on its file's dated rows."""
    own = [
        primary_positive_claim(card, catalogue, external, row_key=era.row_key)
        for card, era in zip(cards, eras, strict=True)
    ]
    by_file: dict[str, list[PositiveClaim]] = {}
    for era, claim in zip(eras, own, strict=True):
        if claim is not None and not era.era_reconciled_from and era.era is not Era.UNDATED:
            by_file.setdefault(file_key(era), []).append(claim)
    return [
        claim
        if claim is not None or not era.era_reconciled_from
        else _strongest(by_file.get(file_key(era), []))
        for era, claim in zip(eras, own, strict=True)
    ]
