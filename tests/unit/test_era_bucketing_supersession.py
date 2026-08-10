"""Tests for claim precedence over the era negative (spec §5, PV1.3/PV1.6).

The 2015+ era negative rests on "a record cannot appear in an archive assembled
before it existed". A positive prior-release claim on the same card is direct
evidence that it did — the government's own description saying so outranks the
era inference. So bucketing must consult the claim chain before emitting a
negative, and record every suppression so the choice is auditable rather than a
silent omission.

"The claim chain" means all of it. The chain has three routes — the Tier-0
sweep, the CREST rule and the catalogue — and the coverage report consults the
same three through the same precedence helper. Handing bucketing a narrower
view would let the two artifacts describe the same card differently: a negative
here, a resolved claim there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import CardEra, Era
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import RESOLVED_BY_CLAIM, classify
from pursue_index.source_index import SourceEntry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"

#: Two manifest cards whose description states a prior release outright.
PANTEX_CARD_ID = "7e0b4624ee81788e"
ODNI_CARD_ID = "fd342b7508668b0e"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def _modern_card(**overrides: object) -> dict:
    card = {
        "card_id": "modern-001",
        "title": "Mission Report, Somewhere, 2023",
        "agency": "DOW",
        "asset_filename": "modern-001.pdf",
        "incident_date": "2023",
        "description": "A routine mission report.",
    }
    card.update(overrides)
    return card


def test_modern_card_without_a_claim_still_takes_the_era_negative() -> None:
    result = bucket({"cards": [_modern_card()]})
    assert [c.card_id for c in result.claims] == ["modern-001"]
    assert result.superseded == []


def test_a_stated_prior_release_suppresses_the_era_negative() -> None:
    card = _modern_card(
        description=(
            "This imagery was originally released on example.gov on May 22, 2026 "
            "in a lower resolution."
        )
    )
    result = bucket({"cards": [card]})
    assert result.claims == []
    assert [row["card_id"] for row in result.superseded] == ["modern-001"]


def test_the_suppression_row_records_the_tier_that_outranked_the_era() -> None:
    card = _modern_card(
        description="Pages 1 and 2 were partially posted on the FBI Vault; some pages missing."
    )
    row = bucket({"cards": [card]}).superseded[0]
    assert row["superseding_tier"] == ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART.value
    assert row["era"] == Era.MODERN_OPERATIONAL.value
    assert row["era_year"] == 2023
    assert row["date_source"] == "incident_date"
    assert row["title"] == "Mission Report, Somewhere, 2023"


def test_the_suppression_row_stands_on_its_own() -> None:
    """A reader judging the suppression has the claim in front of them.

    "Superseded" is a decision not to publish a negative, so the row says what
    outranked it: the tier, where that claim came from, and the wording it rests
    on — rather than a card_id to go and look up in another artifact.
    """
    card = _modern_card(
        description=(
            "This imagery was originally released on dvidshub.net on May 22, 2026 "
            "in a lower resolution."
        )
    )
    row = bucket({"cards": [card]}).superseded[0]
    assert row["superseding_source"] == "war.gov CSV manifest description"
    assert row["superseding_evidence"] == card["description"]


def test_a_catalogue_suppression_names_the_artifact_it_rests_on() -> None:
    """A resolver claim's evidence is the artifact the catalogue resolved to."""
    entry = _catalogue_entry()
    row = bucket({"cards": [_catalogue_only_card()]}, catalogue=[entry]).superseded[0]
    assert row["superseding_source"] == "catalogue"
    assert row["superseding_evidence"] == entry.url


def test_the_reconciliation_note_names_both_causes_of_the_undated_delta() -> None:
    """The delta has two independent causes, and the note distinguishes them.

    Attributing all of it to display-date curation would misdescribe the cards
    that are undated because a two-digit year had nothing to corroborate it —
    a reader reconciling against §4a needs to know which cards to look for.
    """
    note = build_output({"cards": []}, bucket({"cards": []}))["reconciliation_4a"]["note"]
    assert "display_date" in note
    assert "two-digit year" in note
    assert "release_date" in note


def test_a_pre_2015_card_with_a_claim_is_not_a_suppression() -> None:
    """Only the modern era emits a negative, so only it can have one suppressed."""
    card = _modern_card(incident_date="1968", title="Sighting Report, 1968",
                        description="This file was previously released.")
    result = bucket({"cards": [card]})
    assert result.claims == []
    assert result.superseded == []


def test_build_output_publishes_the_suppressions_and_their_count() -> None:
    card = _modern_card(description="This photograph was previously released.")
    manifest = {"cards": [card, _modern_card(card_id="modern-002")]}
    result = bucket(manifest)
    output = build_output(manifest, result)
    assert output["superseded_by_claim_count"] == 1
    assert [row["card_id"] for row in output["superseded_by_claim"]] == ["modern-001"]
    assert output["no_prior_release_count"] == 1


def test_real_manifest_supersedes_the_cards_the_government_describes() -> None:
    """The two manifest cards whose description states a prior release."""
    result = bucket(_manifest())
    superseded = {row["card_id"] for row in result.superseded}
    negatives = {claim.card_id for claim in result.claims}
    assert PANTEX_CARD_ID in superseded
    assert ODNI_CARD_ID in superseded
    assert superseded.isdisjoint(negatives)


# --------------------------------------------------------------------------
# The catalogue is part of the claim chain, so both stages must consult it.
# --------------------------------------------------------------------------


def _catalogue_entry() -> SourceEntry:
    return SourceEntry(
        url="https://documents.theblackvault.com/fbi/62-hq-83894.pdf",
        filename="62-hq-83894.pdf",
        last_modified="Mon, 01 Jun 2015 08:00:00 GMT",
        agency="fbi",
        era="undated",
        era_year=None,
        date_basis=DateBasis.HTTP_LAST_MODIFIED,
    )


def _catalogue_only_card() -> dict:
    """A modern card whose sole positive claim comes from the catalogue.

    Its description asserts nothing, so neither the Tier-0 sweep nor the CREST
    rule reaches it: the only route to a claim is a catalogue match on the file
    number in its title.
    """
    return _modern_card(
        card_id="modern-catalogue",
        title="The 62-HQ-83894 case file records, 2023",
        description="A routine transmittal.",
        release_date="5/8/26",
    )


def test_a_catalogue_resolved_claim_suppresses_the_era_negative() -> None:
    """The catalogue reaches bucketing, so a card it resolves takes no negative."""
    result = bucket({"cards": [_catalogue_only_card()]}, catalogue=[_catalogue_entry()])
    assert result.claims == []
    assert [row["card_id"] for row in result.superseded] == ["modern-catalogue"]
    assert result.superseded[0]["superseding_tier"] == ProvenanceTier.PREVIOUSLY_RELEASED.value


def test_the_same_card_takes_the_negative_when_no_catalogue_is_built() -> None:
    """Without the catalogue there is no claim, so the era conclusion is honest."""
    result = bucket({"cards": [_catalogue_only_card()]})
    assert [c.card_id for c in result.claims] == ["modern-catalogue"]
    assert result.superseded == []


def test_bucketing_and_the_coverage_report_agree_on_the_same_catalogue() -> None:
    """One precedence helper, one catalogue, one answer per card.

    The two artifacts describe the same corpus, so a card the report routes to
    the claim lane must be a card bucketing declines to give a negative — and
    they only stay in step if both hand the same catalogue to the shared helper.
    """
    card = _catalogue_only_card()
    catalogue = [_catalogue_entry()]
    outcome = classify(card, catalogue)
    result = bucket({"cards": [card]}, catalogue=catalogue)
    assert outcome.resolved_by == RESOLVED_BY_CLAIM
    assert outcome.primary_tier == result.superseded[0]["superseding_tier"]


def test_a_modern_negative_needs_a_document_date_and_says_so_without_assert() -> None:
    """The MODERN invariant must hold under ``python -O``, where asserts vanish."""
    from pursue_index.era_bucketing import _no_prior_release

    undated = CardEra(
        card_id="x",
        identifier="x.pdf",
        title="x",
        agency="DOW",
        era=Era.MODERN_OPERATIONAL,
        year=None,
        date_source=None,
        raw_date=None,
    )
    with pytest.raises(ValueError):
        _no_prior_release(undated)
