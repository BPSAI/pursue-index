"""Which positive prior-release claim a card carries, and which one wins.

Two stages need the same answer to the same question — "does this card carry a
positive prior-release claim, and which is the strongest?" — and they must not
answer it differently:

* :mod:`pursue_index.provenance_report` uses it to route a card to the ``claim``
  lane rather than the ``era`` lane.
* :mod:`pursue_index.era_bucketing` uses it to decide whether a 2015+ card may
  take a ``no_prior_release_found`` record at all. The era negative rests on
  "a record cannot appear in an archive assembled before it existed"; a card the
  government's own description says *was* previously released is direct evidence
  against that inference, so the claim outranks the era and the negative is
  suppressed.

Keeping the precedence in one module is the point: an era stage that reimplements
it drifts, and the drift shows up as an artifact asserting a negative the claim
artifact contradicts. Pure computation over an already-loaded card.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from pursue_index.identifier_resolver import resolve_card
from pursue_index.provenance import ProvenanceTier
from pursue_index.resolved_claim import ResolvedClaim
from pursue_index.source_index import SourceEntry
from pursue_index.tier0_sweep import Tier0Claim
from pursue_index.tier0_sweep import detect_claim as detect_tier0_claim

__all__ = [
    "POSITIVE_TIER_PRECEDENCE",
    "PositiveClaim",
    "positive_claims",
    "positive_tiers",
    "primary_positive_claim",
    "primary_positive_tier",
    "primary_tier",
]

#: When a card carries more than one positive tier, the strongest wins as its
#: primary tier. ``previously_released`` (the whole file is established) outranks
#: ``previously_released_in_part`` (only part is), which outranks the weaker
#: ``content_previously_published`` (the content, not this record, is public).
POSITIVE_TIER_PRECEDENCE: tuple[ProvenanceTier, ...] = (
    ProvenanceTier.PREVIOUSLY_RELEASED,
    ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
    ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
)


class PositiveClaim(NamedTuple):
    """A card's positive claim reduced to what a reader of a row needs.

    A stage that records "this card carries a claim" is writing a row someone
    reads on its own, so the row states what backed the claim rather than
    naming another artifact to go and cross-reference. ``source`` is where the
    claim came from; ``evidence`` is what it rests on — the government's own
    verbatim wording for a Tier-0 claim, the resolved artifact or named prior
    publication for a resolver claim.
    """

    tier: ProvenanceTier
    source: str
    evidence: str


def _from_tier0(claim: Tier0Claim) -> PositiveClaim:
    """The government's own description, quoted as it was written."""
    return PositiveClaim(claim.tier, claim.source, claim.evidence)


def _from_resolved(claim: ResolvedClaim) -> PositiveClaim:
    """A resolver claim, evidenced by whatever it resolved to."""
    return PositiveClaim(
        claim.tier, claim.source.value, claim.artifact_url or claim.prior_publication
    )


def positive_claims(
    card: dict[str, Any], catalogue: Sequence[SourceEntry] = ()
) -> list[PositiveClaim]:
    """Every positive prior-release claim the chain asserts for one card."""
    claims: list[PositiveClaim] = []
    tier0 = detect_tier0_claim(card)
    if tier0 is not None:
        claims.append(_from_tier0(tier0))
    claims.extend(_from_resolved(claim) for claim in resolve_card(card, catalogue=catalogue))
    return claims


def positive_tiers(
    card: dict[str, Any], catalogue: Sequence[SourceEntry] = ()
) -> set[ProvenanceTier]:
    """Every positive prior-release tier the chain asserts for one card."""
    return {claim.tier for claim in positive_claims(card, catalogue)}


def primary_tier(tiers: set[ProvenanceTier]) -> ProvenanceTier | None:
    """The strongest tier among a card's positive claims, or ``None``."""
    for tier in POSITIVE_TIER_PRECEDENCE:
        if tier in tiers:
            return tier
    return None


def primary_positive_claim(
    card: dict[str, Any], catalogue: Sequence[SourceEntry] = ()
) -> PositiveClaim | None:
    """The strongest positive claim on a card, with what backs it, or ``None``.

    The catalogue is optional: Tier-0 (the government's description) and the
    CREST rule need none, so a checkout that has never run the catalogue build
    still gets a truthful answer for the cards those routes cover. A stage that
    *does* have a catalogue passes it, so that every stage reads the same chain.
    """
    claims = positive_claims(card, catalogue)
    for tier in POSITIVE_TIER_PRECEDENCE:
        for claim in claims:
            if claim.tier is tier:
                return claim
    return None


def primary_positive_tier(
    card: dict[str, Any], catalogue: Sequence[SourceEntry] = ()
) -> ProvenanceTier | None:
    """The strongest positive tier on a card, or ``None`` if it carries none."""
    claim = primary_positive_claim(card, catalogue)
    return claim.tier if claim is not None else None
