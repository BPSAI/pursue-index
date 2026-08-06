"""Tests for era + agency bucketing (spec §4a/§5, PV1.3).

Every card is assigned an era and an agency from the display-date precedence.
The 2015+ set receives a ``no_prior_release_found`` record carrying its era
rationale and the §5 disclaimer; undated cards surface on an explicit triage
list and are never silently bucketed as modern. ``release_date`` (the war.gov
publication date) is never used as a document era.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.era_bucketing import (
    REFERENCE_4A,
    bucket,
    build_output,
    classify_card,
)
from pursue_index.era_models import (
    ERA_RATIONALE,
    Era,
    EraNoPriorRelease,
    era_for_year,
)
from pursue_index.provenance import NO_PRIOR_RELEASE_DISCLAIMER, ProvenanceTier

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


# --- era_for_year boundaries -------------------------------------------------


@pytest.mark.parametrize(
    "year,expected",
    [
        (2026, Era.MODERN_OPERATIONAL),
        (2015, Era.MODERN_OPERATIONAL),
        (2014, Era.ERA_1990_2014),
        (1990, Era.ERA_1990_2014),
        (1989, Era.ERA_1970_1989),
        (1970, Era.ERA_1970_1989),
        (1969, Era.PRE_1970),
        (1948, Era.PRE_1970),
    ],
)
def test_era_for_year_boundaries(year: int, expected: Era) -> None:
    assert era_for_year(year) == expected


# --- classify_card -----------------------------------------------------------


def test_classify_modern_from_incident_date() -> None:
    ce = classify_card({"card_id": "c1", "agency": "FBI", "incident_date": "2025"})
    assert ce.era is Era.MODERN_OPERATIONAL
    assert ce.year == 2025
    assert ce.date_source == "incident_date"
    assert ce.agency == "FBI"


def test_classify_historical_from_incident_date() -> None:
    ce = classify_card({"card_id": "c2", "agency": "CIA", "incident_date": "3/22/49"})
    assert ce.era is Era.PRE_1970
    assert ce.year == 1949


def test_release_only_card_is_undated_not_modern() -> None:
    # A card whose only date is the war.gov release must NOT be bucketed 2015+.
    ce = classify_card({"card_id": "c3", "agency": "NASA", "release_date": "7/10/26"})
    assert ce.era is Era.UNDATED


def test_no_date_card_is_undated() -> None:
    ce = classify_card({"card_id": "c4", "agency": "FBI"})
    assert ce.era is Era.UNDATED
    assert ce.year is None
    assert ce.date_source is None


def test_missing_agency_defaults_to_unknown() -> None:
    ce = classify_card({"card_id": "c5", "incident_date": "2020"})
    assert ce.agency == "Unknown"


# --- EraNoPriorRelease -------------------------------------------------------


def test_era_no_prior_release_tier_and_disclaimer() -> None:
    rec = EraNoPriorRelease(
        card_id="c1",
        identifier="file.pdf",
        title="A modern report",
        agency="FBI",
        established_year=2025,
        date_source="incident_date",
        established_date="2025",
        rationale=f"dated 2025. {ERA_RATIONALE} {NO_PRIOR_RELEASE_DISCLAIMER}.",
    )
    assert rec.tier is ProvenanceTier.NO_PRIOR_RELEASE_FOUND
    assert rec.disclaimer == NO_PRIOR_RELEASE_DISCLAIMER
    data = rec.to_dict()
    assert data["tier"] == "no_prior_release_found"
    assert data["disclaimer"] == NO_PRIOR_RELEASE_DISCLAIMER
    assert ERA_RATIONALE in data["rationale"]


def test_era_no_prior_release_rejects_pre_2015_year() -> None:
    with pytest.raises(ValueError, match="2015"):
        EraNoPriorRelease(
            card_id="c1", identifier="f", title="t", agency="FBI",
            established_year=1999, date_source="incident_date",
            established_date="1999", rationale=f"x {NO_PRIOR_RELEASE_DISCLAIMER}",
        )


def test_era_no_prior_release_rejects_release_date_basis() -> None:
    with pytest.raises(ValueError, match="document-date"):
        EraNoPriorRelease(
            card_id="c1", identifier="f", title="t", agency="FBI",
            established_year=2025, date_source="release_date",
            established_date="2026", rationale=f"x {NO_PRIOR_RELEASE_DISCLAIMER}",
        )


def test_era_no_prior_release_requires_disclaimer_in_rationale() -> None:
    with pytest.raises(ValueError, match="disclaimer"):
        EraNoPriorRelease(
            card_id="c1", identifier="f", title="t", agency="FBI",
            established_year=2025, date_source="incident_date",
            established_date="2025", rationale="no disclaimer here",
        )


# --- bucket over a small synthetic manifest ----------------------------------


def _synthetic() -> dict:
    return {
        "cards": [
            {"card_id": "m1", "agency": "FBI", "incident_date": "2025", "release_date": "7/10/26"},
            {"card_id": "m2", "agency": "CIA", "incident_date": "1996", "release_date": "7/10/26"},
            {"card_id": "m3", "agency": "NASA", "incident_date": "3/22/49", "release_date": "7/10/26"},
            {"card_id": "m4", "agency": "FBI", "release_date": "7/10/26"},  # release-only -> triage
            {"card_id": "m5", "agency": "FBI"},  # no date -> triage
        ]
    }


def test_bucket_assigns_every_card_an_era_and_agency() -> None:
    result = bucket(_synthetic())
    assert len(result.cards) == 5
    assert all(isinstance(ce.era, Era) and ce.agency for ce in result.cards)
    assert sum(result.era_counts.values()) == 5


def test_bucket_negatives_only_for_modern() -> None:
    result = bucket(_synthetic())
    assert len(result.claims) == 1
    assert result.claims[0].card_id == "m1"
    assert all(c.established_year >= 2015 for c in result.claims)


def test_bucket_undated_surface_as_triage_not_bucketed() -> None:
    result = bucket(_synthetic())
    triaged = {t["card_id"] for t in result.triage}
    assert triaged == {"m4", "m5"}
    assert result.era_counts["undated"] == 2
    # release-only card gives the release-date reason, not "no date"
    m4 = next(t for t in result.triage if t["card_id"] == "m4")
    assert "release_date" in m4["reason"]


def test_bucket_claim_rationale_carries_era_and_section5_wording() -> None:
    claim = bucket(_synthetic()).claims[0]
    assert ERA_RATIONALE in claim.rationale
    assert NO_PRIOR_RELEASE_DISCLAIMER in claim.rationale.lower()


# --- against the real manifest ----------------------------------------------


def test_real_manifest_every_card_bucketed() -> None:
    manifest = _manifest()
    result = bucket(manifest)
    assert len(result.cards) == len(manifest["cards"])
    assert sum(result.era_counts.values()) == len(manifest["cards"])


def test_real_manifest_historical_anchors_match_4a() -> None:
    # pre-1970 and 1970-1989 are fully incident-dated in the corpus, so they
    # reproduce the §4a reference exactly and pin the parser + boundaries.
    counts = bucket(_manifest()).era_counts
    assert counts["pre_1970"] == REFERENCE_4A["pre_1970"]
    assert counts["1970_1989"] == REFERENCE_4A["1970_1989"]


def test_real_manifest_no_release_date_bucketed_as_modern() -> None:
    result = bucket(_manifest())
    assert all(c.date_source in ("display_date", "incident_date") for c in result.claims)


def test_build_output_shape_and_reconciliation() -> None:
    manifest = _manifest()
    out = build_output(manifest, bucket(manifest))
    assert out["card_count"] == len(manifest["cards"])
    assert set(out["era_counts"]) == {e.value for e in Era}
    recon = out["reconciliation_4a"]
    assert recon["reference_4a"] == REFERENCE_4A
    assert set(recon["delta"]) == set(REFERENCE_4A)
    assert out["no_prior_release_count"] == len(out["no_prior_release"])
    assert out["undated_triage_count"] == len(out["undated_triage"])
