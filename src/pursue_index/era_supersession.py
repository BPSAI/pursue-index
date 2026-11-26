"""The published row for a 2015+ negative that a positive claim outranked."""

from __future__ import annotations

from typing import Any

from pursue_index.claim_precedence import PositiveClaim
from pursue_index.era_models import CardEra

__all__ = ["CLAIM_RESOLVED_REASON", "SUPERSEDED_REASON", "claim_resolved_entry", "superseded_entry"]

#: Why a modern card can lose its negative — recorded on every suppression row.
SUPERSEDED_REASON = (
    "A positive prior-release claim was found for this card, so the era-based "
    "no-prior-release conclusion does not apply: the claim is evidence the "
    "record did appear before this archive was assembled."
)

def superseded_entry(
    card_era: CardEra, claim: PositiveClaim, inherited_from: str | None = None, date_conflict: str | None = None
) -> dict[str, Any]:
    """Record a negative that a positive claim outranked — never a silent drop.

    The row states what outranked the era conclusion, not just that something
    did: the tier, where the claim came from, and the evidence it rests on. A
    reader deciding whether the suppression was right has it all here, rather
    than having to match this card against another artifact by hand.

    ``date_conflict`` is the conflict reason of an inheriting row's file: the record carries
    ``date_conflict: true`` and ``date_conflict_reason``, so the conflict stays visible
    once the row has left triage.
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
        **({"era_reconciled_from": card_era.era_reconciled_from} if card_era.era_reconciled_from else {}),
        **({"claim_inherited_from": inherited_from} if inherited_from else {}),
        **({"date_conflict": True, "date_conflict_reason": date_conflict} if date_conflict else {}),
    }


#: Why a claimed row that is not modern emits no negative and no triage entry.
CLAIM_RESOLVED_REASON = (
    "A positive prior-release claim, this row's own or its file's, resolves this "
    "row, so it needs neither an era negative nor triage."
)


def claim_resolved_entry(
    card_era: CardEra, claim: PositiveClaim, inherited_from: str | None = None, date_conflict: str | None = None
) -> dict[str, Any]:
    """Record a row a claim resolves that is not a modern negative: same fields, its own reason."""
    return {**superseded_entry(card_era, claim, inherited_from, date_conflict), "reason": CLAIM_RESOLVED_REASON}
