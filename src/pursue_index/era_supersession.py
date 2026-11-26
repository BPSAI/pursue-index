"""The published row for a 2015+ negative that a positive claim outranked."""

from __future__ import annotations

from typing import Any

from pursue_index.claim_precedence import PositiveClaim
from pursue_index.era_models import CardEra

__all__ = ["SUPERSEDED_REASON", "superseded_entry"]

#: Why a modern card can lose its negative — recorded on every suppression row.
SUPERSEDED_REASON = (
    "A positive prior-release claim was found for this card, so the era-based "
    "no-prior-release conclusion does not apply: the claim is evidence the "
    "record did appear before this archive was assembled."
)

def superseded_entry(card_era: CardEra, claim: PositiveClaim) -> dict[str, Any]:
    """Record a negative that a positive claim outranked — never a silent drop.

    The row states what outranked the era conclusion, not just that something
    did: the tier, where the claim came from, and the evidence it rests on. A
    reader deciding whether the suppression was right has it all here, rather
    than having to match this card against another artifact by hand.
    """
    return {
        "card_id": card_era.card_id,
        "row_key": card_era.row_key,
        "identifier": card_era.identifier,
        "title": card_era.title,
        "agency": card_era.agency,
        "era": card_era.era.value,
        "era_year": card_era.year,
        "date_source": card_era.date_source,
        "superseding_tier": claim.tier.value,
        "superseding_source": claim.source,
        "superseding_evidence": claim.evidence,
        "reason": SUPERSEDED_REASON,
    }
