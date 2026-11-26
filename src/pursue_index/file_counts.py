"""The source file is the unit of a headline count.

Rows sharing a ``card_id`` name one file, so a headline count is over files, not
rows. Once a file's rows are reconciled a file has one era; a file whose dated rows
conflict has none and is counted once under ``undated``. A row with no ``card_id`` is
a file of its own.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from typing import Any

from pursue_index.claim_precedence import unkeyed_claims
from pursue_index.era_models import CardEra, Era, EraNoPriorRelease
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.row_key import file_part

__all__ = ["count_fields", "file_eras", "file_key", "file_key_of", "tallies"]

def file_key_of(card_id: str, row_key: str) -> str:
    """The file identity rule: the ``card_id``, or the file part of the row's key when it has none."""
    return card_id or file_part(row_key)


def file_key(card: CardEra | EraNoPriorRelease) -> str:
    """The file a row belongs to: its ``card_id``, or its own ``no-card-id-<i>`` key when it has none."""
    return file_key_of(card.card_id, card.row_key)


def file_eras(cards: Sequence[CardEra], conflicts: Collection[str] = ()) -> dict[str, str]:
    """One era value per file; ``undated`` for a file whose dated rows conflict."""
    seen: dict[str, set[str]] = {}
    for card in cards:
        seen.setdefault(file_key(card), set()).add(card.era.value)
    conflicted = {file_key(card) for card in cards if card.row_key in conflicts}
    return {
        key: next(iter(eras)) if len(eras) == 1 and key not in conflicted else Era.UNDATED.value
        for key, eras in seen.items()
    }


#: The agency a file is counted under when its rows name more than one.
MIXED_AGENCY = "mixed"


def file_agencies(cards: Sequence[CardEra]) -> dict[str, str]:
    """One agency per file: its rows' agency, or ``mixed`` when they disagree."""
    seen: dict[str, set[str]] = {}
    for card in cards:
        seen.setdefault(file_key(card), set()).add(card.agency)
    return {key: next(iter(agencies)) if len(agencies) == 1 else MIXED_AGENCY for key, agencies in seen.items()}


def tallies(
    cards: Sequence[CardEra], conflicts: Collection[str] = ()
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    """Era counts per file and per row, and agency counts per file and per row.

    The two era maps must share one key set (every era, zeros included); a producer that
    would emit them differently raises rather than publish counts that cannot be compared.
    """
    per_file = {era.value: 0 for era in Era}
    per_file.update(Counter(file_eras(cards, conflicts).values()))
    per_row = {era.value: 0 for era in Era}
    per_row.update(Counter(card.era.value for card in cards))
    if per_file.keys() != per_row.keys():
        raise ValueError(f"era_file_counts and era_row_counts differ in keys: {sorted(per_file.keys() ^ per_row.keys())}")
    agency_file = dict(sorted(Counter(file_agencies(cards).values()).items()))
    return per_file, per_row, agency_file, dict(sorted(Counter(card.agency for card in cards).items()))


def count_fields(
    cards: Sequence[CardEra],
    claims: Sequence[EraNoPriorRelease],
    external: Sequence[ResolvedClaim] = (),
    conflicts: Collection[str] = (),
) -> dict[str, Any]:
    """The count-bearing ``BucketResult`` fields: per file, per row, and unkeyed claims."""
    era_file_counts, era_row_counts, agency_file_counts, agency_row_counts = tallies(cards, conflicts)
    return {
        "era_file_counts": era_file_counts,
        "era_row_counts": era_row_counts,
        "file_count": len(file_eras(cards, conflicts)),
        "no_prior_release_files": list(dict.fromkeys(file_key(claim) for claim in claims)),
        "unkeyed_claim_count": unkeyed_claims(external),
        "agency_file_counts": agency_file_counts,
        "agency_row_counts": agency_row_counts,
    }
