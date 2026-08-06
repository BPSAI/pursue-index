"""Tests for the identifier resolver and its typed claims (PV1.5).

The resolver turns extracted identifiers into typed provenance claims, but only
when they resolve to a real artifact — a catalogue entry or a known public
archive. A search-engine snippet never produces a claim. And it holds two lines
the doctrine draws:

* Content that is public but whose *specific record's* release is unestablished
  emits ``content_previously_published``, not ``previously_released`` (the COMETA
  case, spec §6c).
* An identifier match against a *subset of an omnibus file* never emits
  ``previously_released``; it emits ``previously_released_in_part`` and flags the
  card for later page-image comparison.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pursue_index.identifier_resolver import (
    CREST_ONLINE_RELEASE,
    build_output,
    is_omnibus_subset,
    resolve_against_catalogue,
    resolve_card,
    resolve_content_published,
)
from pursue_index.identifiers import IdentifierKind
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.source_index import SourceEntry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _cards() -> list[dict]:
    return json.loads(_MANIFEST.read_text())["cards"]


def _card_by_title(fragment: str) -> dict:
    for card in _cards():
        if fragment in (card.get("title") or ""):
            return card
    raise AssertionError(f"no card whose title contains {fragment!r}")


def _entry(url: str, last_modified: str | None) -> SourceEntry:
    from urllib.parse import urlparse

    return SourceEntry(
        url=url,
        filename=urlparse(url).path.rsplit("/", 1)[-1],
        last_modified=last_modified,
        agency="unknown",
        era="undated",
        era_year=None,
    )


# --------------------------------------------------------------------------
# CIA CREST resolves via the public online-release construction rule.
# --------------------------------------------------------------------------


def test_crest_id_resolves_to_readingroom_artifact_with_date_basis() -> None:
    card = {"card_id": "c1", "title": "Doc CIA-RDP79B00752A000300070001-6"}
    claims = resolve_card(card)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED
    assert claim.identifier_kind == IdentifierKind.CIA_CREST.value
    assert claim.artifact_url == (
        "https://www.cia.gov/readingroom/document/"
        "cia-rdp79b00752a000300070001-6"
    )
    # The CREST collection went online 2017-01-17 — a stated publisher date.
    assert claim.established_date == CREST_ONLINE_RELEASE
    assert claim.date_basis is DateBasis.PUBLISHER_DATE
    assert claim.source is ResolutionSource.KNOWN_ARCHIVE


# --------------------------------------------------------------------------
# FBI / Blue Book resolve against the catalogue (fixture-injected).
# --------------------------------------------------------------------------


def test_fbi_file_resolves_against_catalogue_with_http_date_basis() -> None:
    card = {"card_id": "fbi1", "title": "The 62-HQ-83894 case file records"}
    catalogue = [
        _entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf", "Wed, 30 May 2018 10:00:00 GMT"),
    ]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.identifier_kind == IdentifierKind.FBI_FILE.value
    assert claim.artifact_url == "https://documents.theblackvault.com/fbi/62-hq-83894.pdf"
    assert claim.established_date == date(2018, 5, 30)
    assert claim.date_basis is DateBasis.HTTP_LAST_MODIFIED
    assert claim.source is ResolutionSource.CATALOGUE


def test_short_case_number_does_not_substring_match_an_unrelated_url() -> None:
    # A bare case number must be a bounded token, not any substring — else a
    # short number would emit a false citation against an unrelated artifact.
    card = {"card_id": "bb2", "title": "Project Blue Book Case No. 10073 report"}
    catalogue = [
        _entry("https://documents.theblackvault.com/misc/file-2010073-x.pdf", "Mon, 01 Jun 2015 08:00:00 GMT"),
    ]
    assert resolve_card(card, catalogue=catalogue) == []


def test_fbi_file_matches_across_separator_variants() -> None:
    card = {"card_id": "fbi9", "title": "The 62-HQ-83894 case file records"}
    catalogue = [
        _entry("https://documents.theblackvault.com/fbi/62_hq_83894_section_1.pdf", "Wed, 30 May 2018 10:00:00 GMT"),
    ]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].identifier_kind == IdentifierKind.FBI_FILE.value


def test_blue_book_case_resolves_against_catalogue() -> None:
    card = {"card_id": "bb1", "title": "Project Blue Book Case No. 10073 report"}
    catalogue = [
        _entry("https://documents.theblackvault.com/bluebook/case-10073.pdf", "Mon, 01 Jun 2015 08:00:00 GMT"),
    ]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].identifier_kind == IdentifierKind.BLUE_BOOK_CASE.value
    assert claims[0].date_basis is DateBasis.HTTP_LAST_MODIFIED


# --------------------------------------------------------------------------
# A claim only when it resolves to an artifact; snippets never do.
# --------------------------------------------------------------------------


def test_identifier_with_no_artifact_produces_no_claim() -> None:
    card = {"card_id": "fbi2", "title": "The 62-HQ-83894 case file records"}
    # Empty catalogue, no CREST id -> nothing resolves -> no claim.
    assert resolve_card(card, catalogue=[]) == []


def test_catalogue_entry_without_a_date_is_not_claimed() -> None:
    # No Last-Modified => we cannot date the claim honestly => skip it.
    card = {"card_id": "fbi3", "title": "The 62-HQ-83894 case file records"}
    catalogue = [_entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf", None)]
    assert resolve_against_catalogue(card, next(iter(_extract(card))), catalogue) is None


def _extract(card: dict) -> list:
    from pursue_index.identifiers import extract_identifiers

    return extract_identifiers(card)


def test_resolved_claim_refuses_a_search_snippet_source() -> None:
    with pytest.raises(ValueError):
        ResolvedClaim(
            card_id="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            source=ResolutionSource.SEARCH_SNIPPET,
            artifact_url="https://example.com/x.pdf",
            established_date=date(2020, 1, 1),
            date_basis=DateBasis.PUBLISHER_DATE,
        )


# --------------------------------------------------------------------------
# COMETA: content public, this record's release unestablished (spec §6c).
# --------------------------------------------------------------------------


def test_cometa_emits_content_previously_published_not_previously_released() -> None:
    card = _card_by_title("UFO's_and_Defense")
    claim = resolve_content_published(card)
    assert claim is not None
    assert claim.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED
    assert "VDS" in claim.prior_publication
    # Year-only publication: no forged full calendar date.
    assert claim.established_date is None
    assert claim.date_basis is None
    assert claim.source is ResolutionSource.GOVERNMENT_DESCRIPTION


def test_cometa_card_never_emits_a_previously_released_claim() -> None:
    # This card is also the 255_413270 false-NAID case: it must not produce a
    # previously_released claim from the record-group finding-aid number.
    card = _card_by_title("UFO's_and_Defense")
    claims = resolve_card(card)
    assert all(c.tier is not ProvenanceTier.PREVIOUSLY_RELEASED for c in claims)
    assert any(c.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED for c in claims)


# --------------------------------------------------------------------------
# Omnibus subset: never previously_released; always in_part + flag.
# --------------------------------------------------------------------------


def test_omnibus_section_is_detected() -> None:
    assert is_omnibus_subset({"title": "65_..._62-HQ-83894_Section_001"})
    assert is_omnibus_subset({"title": "x", "description": "some pages missing here"})
    assert not is_omnibus_subset({"title": "A single standalone report"})


def test_omnibus_subset_downgrades_previously_released_to_in_part() -> None:
    card = {"card_id": "sec", "title": "62-HQ-83894 Section 001 of the case file"}
    catalogue = [
        _entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf", "Wed, 30 May 2018 10:00:00 GMT"),
    ]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART
    assert claim.needs_page_image_comparison is True


def test_crest_in_an_omnibus_card_is_also_downgraded() -> None:
    card = {"card_id": "c2", "title": "CIA-RDP79B00752A000300070001-6 Section 002"}
    claims = resolve_card(card)
    assert claims[0].tier is ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART
    assert claims[0].needs_page_image_comparison is True


# --------------------------------------------------------------------------
# ResolvedClaim dataclass invariants.
# --------------------------------------------------------------------------


def test_strong_tier_requires_artifact_url_and_date() -> None:
    with pytest.raises(ValueError):
        ResolvedClaim(
            card_id="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            source=ResolutionSource.CATALOGUE,
            artifact_url="",  # missing
            established_date=date(2020, 1, 1),
            date_basis=DateBasis.HTTP_LAST_MODIFIED,
        )


def test_page_image_flag_belongs_only_to_in_part() -> None:
    with pytest.raises(ValueError):
        ResolvedClaim(
            card_id="x",
            tier=ProvenanceTier.PREVIOUSLY_RELEASED,
            source=ResolutionSource.CATALOGUE,
            artifact_url="https://example.com/x.pdf",
            established_date=date(2020, 1, 1),
            date_basis=DateBasis.HTTP_LAST_MODIFIED,
            needs_page_image_comparison=True,
        )


def test_negative_tier_is_rejected() -> None:
    with pytest.raises(ValueError):
        ResolvedClaim(
            card_id="x",
            tier=ProvenanceTier.NO_PRIOR_RELEASE_FOUND,
            source=ResolutionSource.CATALOGUE,
        )


def test_content_published_requires_artifact_or_prior_publication() -> None:
    with pytest.raises(ValueError):
        ResolvedClaim(
            card_id="x",
            tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
            source=ResolutionSource.GOVERNMENT_DESCRIPTION,
        )


def test_roundtrip_to_dict_from_dict() -> None:
    claim = ResolvedClaim(
        card_id="x",
        tier=ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART,
        source=ResolutionSource.CATALOGUE,
        identifier_kind=IdentifierKind.FBI_FILE.value,
        identifier_value="62-HQ-83894",
        artifact_url="https://example.com/x.pdf",
        established_date=date(2018, 5, 30),
        date_basis=DateBasis.HTTP_LAST_MODIFIED,
        needs_page_image_comparison=True,
    )
    assert ResolvedClaim.from_dict(claim.to_dict()) == claim


# --------------------------------------------------------------------------
# Output artifact.
# --------------------------------------------------------------------------


def test_build_output_reports_counts_and_catalogue_state() -> None:
    manifest = {"cards": _cards(), "source_url": "u", "csv_sha256": "abc"}
    claims = []
    for card in manifest["cards"]:
        claims.extend(resolve_card(card))
    out = build_output(manifest, claims, catalogue_entries=0)
    assert out["card_count"] == len(manifest["cards"])
    assert out["claim_count"] == len(claims)
    assert out["catalogue_entries"] == 0
    # With no catalogue, COMETA still resolves from the government description.
    assert any(
        c["tier"] == ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED.value for c in out["claims"]
    )
