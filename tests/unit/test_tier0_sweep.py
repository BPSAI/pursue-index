"""Tests for the Tier-0 government-CSV provenance sweep (spec §5, PV1.2).

The releasing agency's own description field is the highest-authority
provenance source available and it is already ingested in every manifest.
This sweep reads ``data/manifests/latest.json`` and, for every card whose
description *asserts* a prior release, FOIA history or declassification,
emits a typed Tier-0 claim that reuses the :class:`ProvenanceTier` taxonomy
from PV1.1 and preserves the government's wording **verbatim** as evidence.

The bar is precision over recall: a description that merely uses a word like
"released" (in "never before released") or "previously" (in "previously
observed") must *not* produce a claim. The rejected cases are covered here so
the sweep cannot silently start over-claiming.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pursue_index.provenance import POSITIVE_TIERS, DateBasis, ProvenanceTier
from pursue_index.tier0_sweep import (
    Tier0Claim,
    build_output,
    detect_claim,
    sweep,
    sweep_file,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def _cards() -> list[dict]:
    return _manifest()["cards"]


def _card_by_title(fragment: str) -> dict:
    for card in _cards():
        if fragment in (card.get("title") or ""):
            return card
    raise AssertionError(f"no card whose title contains {fragment!r}")


# --------------------------------------------------------------------------
# True positives — the government asserts a prior release / declassification.
# --------------------------------------------------------------------------


def test_fbi_62hq_rows_resolve_to_previously_released_in_part() -> None:
    card = _card_by_title("62-HQ-83894")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART
    # The government's own wording, verbatim, is the evidence.
    assert "partially posted on FBI vault" in claim.evidence
    assert "some pages missing" in claim.evidence
    assert claim.evidence in card["description"]


def test_every_fbi_section_and_serial_is_claimed_in_part() -> None:
    fbi = [c for c in _cards() if "62-HQ-83894" in (c.get("title") or "")]
    assert len(fbi) >= 18
    for card in fbi:
        claim = detect_claim(card)
        assert claim is not None, card["title"]
        assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART


def test_pantex_originally_released_in_more_redacted_form_with_date() -> None:
    card = _card_by_title("DOE-UAP-D005")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART
    assert claim.stated_date == date(2026, 5, 22)
    assert claim.date_basis is DateBasis.PUBLISHER_DATE
    assert "originally released" in claim.evidence
    assert "more redacted form" in claim.evidence
    assert claim.evidence in card["description"]


def test_cometa_content_previously_published_year_only_no_forged_date() -> None:
    card = _card_by_title("UFO's_and_Defense")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED
    assert "previously published in the French magazine VDS in 1999" in claim.evidence
    # A bare year is not a full calendar date — the model must not forge one.
    assert claim.stated_date is None
    assert claim.date_basis is None


def test_odni_accompanying_imagery_previously_released_with_date() -> None:
    card = _card_by_title("ODNI-UAP-D001")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert claim.stated_date == date(2026, 5, 8)
    assert claim.date_basis is DateBasis.PUBLISHER_DATE
    assert "war.gov" in claim.prior_source
    assert claim.evidence in card["description"]


def test_apollo_photo_previously_released() -> None:
    card = _card_by_title("NASA-UAP-VM006")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert "previously released and discussed" in claim.evidence


def test_cia019_document_released_by_national_archives_of_australia() -> None:
    card = _card_by_title("CIA-UAP-019")
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert "National Archives of Australia" in claim.prior_source
    assert claim.evidence in card["description"]


# --------------------------------------------------------------------------
# Precision — trigger-shaped words that do NOT assert a prior release.
# --------------------------------------------------------------------------


def test_never_before_released_is_not_a_prior_release() -> None:
    # CIA-UAP-017 says "never before released" (with non-breaking spaces).
    card = _card_by_title("CIA-UAP-017")
    assert "released" in (card["description"].lower())
    assert detect_claim(card) is None


def test_previously_observed_is_not_previously_released() -> None:
    card = _card_by_title("FBI-UAP-D008")
    assert "previously" in card["description"].lower()
    assert detect_claim(card) is None


def test_previously_expressed_is_not_a_prior_release() -> None:
    card = _card_by_title("NASA-UAP-D023")
    assert detect_claim(card) is None


def test_bare_prior_in_chain_of_custody_is_not_a_prior_release() -> None:
    card = _card_by_title("DOW-UAP-PR052")
    assert "prior" in card["description"].lower()
    assert detect_claim(card) is None


def test_generic_foia_mention_produces_no_claim() -> None:
    card = {
        "card_id": "synthetic-foia",
        "title": "Synthetic generic FOIA card",
        "description": (
            "This record is releasable in full. Portions of related files may "
            "be withheld under FOIA exemptions (b)(1) and (b)(3)."
        ),
    }
    assert detect_claim(card) is None


def test_prior_release_via_foia_still_claims() -> None:
    # FOIA in a *generic* sense is rejected, but an explicit prior release is
    # still a claim even when the word FOIA appears.
    card = {
        "card_id": "synthetic-foia-release",
        "title": "Synthetic prior FOIA release",
        "description": (
            "These pages were previously released and discussed under a FOIA "
            "request before this collection was assembled."
        ),
    }
    claim = detect_claim(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED


def test_ordinary_card_produces_no_claim() -> None:
    card = _card_by_title("DOE-UAP-D004")  # the Los Alamos green-fireballs card
    assert detect_claim(card) is None


# --------------------------------------------------------------------------
# Sweep-wide invariants.
# --------------------------------------------------------------------------


def test_sweep_claims_are_all_positive_tiers_and_verbatim() -> None:
    cards = _cards()
    by_id = {c["card_id"]: c for c in cards}
    claims = sweep(_manifest())
    assert claims  # the manifest is known to carry prior-release language
    for claim in claims:
        assert claim.tier in POSITIVE_TIERS
        # Never the honest-negative tier.
        assert claim.tier is not ProvenanceTier.NO_PRIOR_RELEASE_FOUND
        # Evidence is an exact substring of the source description.
        assert claim.evidence in (by_id[claim.card_id].get("description") or "")


def test_sweep_file_matches_in_memory_sweep() -> None:
    from_file = sweep_file(_MANIFEST)
    in_memory = sweep(_manifest())
    assert [c.card_id for c in from_file] == [c.card_id for c in in_memory]


def test_sweep_includes_all_eighteen_fbi_rows() -> None:
    claims = sweep(_manifest())
    fbi = [c for c in claims if c.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART]
    fbi_titles = [c for c in claims if "62-HQ-83894" in c.title]
    assert len(fbi_titles) >= 18
    assert all(c.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART for c in fbi_titles)
    assert len(fbi) >= 18


# --------------------------------------------------------------------------
# Output artifact + dataclass guards.
# --------------------------------------------------------------------------


def test_build_output_preserves_manifest_provenance_and_counts() -> None:
    manifest = _manifest()
    claims = sweep(manifest)
    out = build_output(manifest, claims)
    assert out["claim_count"] == len(claims)
    assert out["card_count"] == len(manifest["cards"])
    assert out["csv_sha256"] == manifest.get("csv_sha256")
    assert out["source_manifest"] == manifest.get("source_url")
    assert len(out["claims"]) == len(claims)
    first = out["claims"][0]
    assert first["tier"] in {t.value for t in POSITIVE_TIERS}
    assert first["evidence"]


def test_claim_rejects_the_negative_tier() -> None:
    with pytest.raises(ValueError):
        Tier0Claim(
            card_id="x",
            identifier="x",
            title="x",
            tier=ProvenanceTier.NO_PRIOR_RELEASE_FOUND,
            evidence="something",
            prior_source="somewhere",
        )


def test_claim_requires_nonblank_evidence() -> None:
    with pytest.raises(ValueError):
        Tier0Claim(
            card_id="x",
            identifier="x",
            title="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            evidence="   ",
            prior_source="somewhere",
        )


def test_claim_date_and_basis_travel_together() -> None:
    # A stated date without a basis (or vice versa) is unrepresentable.
    with pytest.raises(ValueError):
        Tier0Claim(
            card_id="x",
            identifier="x",
            title="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            evidence="e",
            prior_source="s",
            stated_date=date(2020, 1, 1),
        )
