"""Tests for what a Tier-0 sweep does with a source it cannot name (PV1.2).

The rules are ordered most-specific first and the first one to match settles
what the description asserts. That match is the reading of the card: it fixes
both the tier and the source the government pointed at.

So when the matched rule captures a source that is not an address a reader can
follow, the card yields no claim. The alternative — carrying on down the list
until some weaker rule matches — would emit a *different* tier attached to that
rule's own static label, attributing the release to a source the description
never named. A card with no claim is the honest outcome, and the count of cards
in that position is published so the gap is visible in the artifact rather than
only on a console.
"""

from __future__ import annotations

from pursue_index.provenance import ProvenanceTier
from pursue_index.tier0_sweep import (
    UNCITABLE_PRIOR_SOURCE_REASON,
    build_output,
    detect_claim,
    sweep,
)


def _card(description: str, card_id: str = "t0-skip-1") -> dict:
    return {
        "card_id": card_id,
        "title": "ODNI-UAP-D001, Narrative",
        "asset_filename": f"{card_id}.pdf",
        "description": description,
    }


#: The most specific rule matches and names ``data:``; a later, weaker rule
#: would match "previously released" and label it "prior public release".
_TWO_RULE_DESCRIPTION = (
    "This imagery was originally released on data:text/html,x on May 22, 2026. "
    "It was previously released in a lower resolution."
)


def test_a_matched_rule_that_names_no_address_yields_no_claim() -> None:
    assert detect_claim(_card(_TWO_RULE_DESCRIPTION)) is None


def test_the_weaker_rule_below_it_does_not_supply_a_different_source() -> None:
    """The second sentence alone does claim, which is what makes the pair a test."""
    claim = detect_claim(_card("It was previously released in a lower resolution."))
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert claim.prior_source == "prior public release"


def test_the_sweep_counts_every_card_it_could_not_name_a_source_for() -> None:
    manifest = {
        "cards": [
            _card(_TWO_RULE_DESCRIPTION),
            _card("Originally released on javascript:alert(1) on May 22, 2026.", "t0-skip-2"),
            _card("It was previously released in a lower resolution.", "t0-ok"),
        ]
    }
    result = sweep(manifest)
    assert [c.card_id for c in result.claims] == ["t0-ok"]
    assert result.uncitable_prior_source == 2


def test_the_artifact_publishes_that_count_and_why() -> None:
    manifest = {"cards": [_card(_TWO_RULE_DESCRIPTION)]}
    output = build_output(manifest, sweep(manifest))
    assert output["claim_count"] == 0
    assert output["uncitable_prior_source_skipped"]["count"] == 1
    assert output["uncitable_prior_source_skipped"]["reason"] == UNCITABLE_PRIOR_SOURCE_REASON


def test_a_card_whose_named_source_is_an_address_is_not_counted_as_a_skip() -> None:
    manifest = {"cards": [_card("Originally released on dvidshub.net on May 22, 2026.")]}
    result = sweep(manifest)
    assert [c.prior_source for c in result.claims] == ["dvidshub.net"]
    assert result.uncitable_prior_source == 0
