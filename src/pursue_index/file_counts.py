"""The source file is the unit of a headline count.

Rows sharing a ``card_id`` name one file, so a headline count is over files, not
rows. A file whose rows all land in one era has that era. A file whose rows land
in different eras has no single era without reconciling them, so it is counted
once under the explicit key ``mixed``. This is a placeholder: each row keeps its
own era, and a later change that reconciles a file's rows replaces it. A row with
no ``card_id`` is a file of its own.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pursue_index.claim_precedence import unkeyed_claims
from pursue_index.era_models import CardEra, Era, EraNoPriorRelease
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.row_key import file_part

__all__ = ["MIXED", "count_fields", "file_eras", "file_key", "file_key_of", "tallies"]

#: The per-file era of a file whose rows land in different eras.
MIXED = "mixed"


def file_key_of(card_id: str, row_key: str) -> str:
    """The file identity rule: the ``card_id``, or the file part of the row's key when it has none."""
    return card_id or file_part(row_key)


def file_key(card: CardEra | EraNoPriorRelease) -> str:
    """The file a row belongs to: its ``card_id``, or its own ``no-card-id-<i>`` key when it has none."""
    return file_key_of(card.card_id, card.row_key)


def file_eras(cards: Sequence[CardEra]) -> dict[str, str]:
    """One era value per file; ``mixed`` when the file's rows land in different eras."""
    seen: dict[str, set[str]] = {}
    for card in cards:
        seen.setdefault(file_key(card), set()).add(card.era.value)
    return {key: next(iter(eras)) if len(eras) == 1 else MIXED for key, eras in seen.items()}


def tallies(cards: Sequence[CardEra]) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Era counts per file and per row (the same keys, ``mixed`` included), and agency counts per row."""
    per_file = {era.value: 0 for era in Era} | {MIXED: 0}
    per_file.update(Counter(file_eras(cards).values()))
    per_row = {era.value: 0 for era in Era} | {MIXED: 0}
    per_row.update(Counter(card.era.value for card in cards))
    return per_file, per_row, dict(sorted(Counter(card.agency for card in cards).items()))


def count_fields(
    cards: Sequence[CardEra],
    claims: Sequence[EraNoPriorRelease],
    external: Sequence[ResolvedClaim] = (),
) -> dict[str, Any]:
    """The count-bearing ``BucketResult`` fields: per file, per row, and unkeyed claims."""
    era_file_counts, era_row_counts, agency_row_counts = tallies(cards)
    return {
        "era_file_counts": era_file_counts,
        "era_row_counts": era_row_counts,
        "file_count": len(file_eras(cards)),
        "no_prior_release_files": list(dict.fromkeys(file_key(claim) for claim in claims)),
        "claims_without_row_key": unkeyed_claims(external),
        "agency_row_counts": agency_row_counts,
    }
