"""LS1.4 — GEO discovery metadata must not drift between tranches.

`llms.txt` and `llms-full.txt` are hand-maintained today: nothing regenerates
them and nothing checks them, so a tranche that adds cards silently leaves them
describing the previous release. These tests pin both halves of the fix — the
regeneration of the manifest-derived sections, and the staleness check that
fails the ship step when they disagree with the manifest.

Scope note: a tranche changes cards, counts and the manifest sha. It does not
change the hand-written prose sections or the editorial `/finds` articles that
`llms-full.txt` inlines. So the generator rewrites the derived sections and
preserves everything else verbatim.
"""

from __future__ import annotations

import pytest

from pursue_index.geo.llms import (
    GeoFreshness,
    build_cards_intro,
    build_provenance_line,
    card_display_date,
    card_index_line,
    check_geo_freshness,
    parse_existing_excerpts,
    parse_provenance,
    render_card_detail,
    replace_section,
    resolve_excerpt,
    should_include_excerpt,
)

SITE = "https://pursueindex.com"


def _card(**over):
    base = {
        "card_id": "81a3947abfb387af",
        "title": "DOE-UAP-D004, Los Alamos Conference on Aerial Phenomena, 1949",
        "agency": "Department of Energy",
        "display_date": "3/22/49",
        "asset_url": "https://www.war.gov/x/DOE-UAP-D004.pdf",
        "description": "A 1949 Los Alamos conference transcript.",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# Index lines (llms.txt "## Cards")
# --------------------------------------------------------------------------


def test_card_index_line_matches_the_published_format() -> None:
    assert card_index_line(_card()) == (
        "- [81a3947abfb387af — DOE-UAP-D004, Los Alamos Conference on Aerial "
        f"Phenomena, 1949]({SITE}/card/81a3947abfb387af): Department of Energy (3/22/49)."
    )


def test_card_index_line_omits_the_date_parenthetical_when_absent() -> None:
    line = card_index_line(
        _card(display_date=None, incident_date=None, release_date=None)
    )
    assert line.endswith(": Department of Energy.")
    assert "()" not in line


# The curation overlay is not yet populated for any card, so reading only
# `display_date` would silently drop the date from all 334 entries.
@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"display_date": "1949", "incident_date": "3/22/49"}, "1949"),
        ({"display_date": None, "incident_date": "3/22/49"}, "3/22/49"),
        ({"display_date": None, "incident_date": None, "release_date": "5/8/26"}, "5/8/26"),
        ({"display_date": None, "incident_date": None, "release_date": None}, None),
    ],
)
def test_display_date_precedence(fields: dict, expected: str | None) -> None:
    """Curated overlay wins, then the CSV incident date, then the release date."""
    assert card_display_date(_card(**fields)) == expected


# --------------------------------------------------------------------------
# Detail entries (llms-full.txt "## Cards")
# --------------------------------------------------------------------------


def test_render_card_detail_includes_source_and_excerpt() -> None:
    out = render_card_detail(_card(), excerpt="SECRET TRANSMITTAL ...")

    assert out.startswith("### 81a3947abfb387af — DOE-UAP-D004")
    assert f"- URL: {SITE}/card/81a3947abfb387af" in out
    assert "- Source: https://www.war.gov/x/DOE-UAP-D004.pdf" in out
    assert "Excerpt (page 1):" in out
    assert "SECRET TRANSMITTAL ..." in out


def test_render_card_detail_omits_source_line_when_asset_url_is_null() -> None:
    """Video/withdrawn cards carry no asset_url; the line must vanish, not render None."""
    out = render_card_detail(_card(asset_url=None), excerpt=None)

    assert "- Source:" not in out
    assert "None" not in out


def test_render_card_detail_omits_excerpt_block_when_ocr_is_unavailable() -> None:
    """OCR lives on the NAS tier; a machine without it must still emit valid output."""
    out = render_card_detail(_card(), excerpt=None)

    assert "Excerpt" not in out
    assert out.rstrip().endswith("A 1949 Los Alamos conference transcript.")


# --------------------------------------------------------------------------
# Section replacement — derived sections only, prose preserved
# --------------------------------------------------------------------------


def test_replace_section_rewrites_only_the_named_section() -> None:
    doc = "# Title\n\nblurb\n\n## Meta\n\n- keep me\n\n## Cards\n\n- old card\n\n## Finds\n\n- keep me too\n"

    out = replace_section(doc, "Cards", "- new card")

    assert "- new card" in out
    assert "- old card" not in out
    assert "- keep me\n" in out
    assert "- keep me too" in out
    assert out.index("## Meta") < out.index("## Cards") < out.index("## Finds")


def test_replace_section_is_idempotent() -> None:
    doc = "# T\n\n## Cards\n\n- a\n\n## Finds\n\n- f\n"
    once = replace_section(doc, "Cards", "- b")

    assert replace_section(once, "Cards", "- b") == once


def test_replace_section_rejects_a_missing_section_rather_than_appending() -> None:
    """Silently appending would corrupt document order and hide a rename."""
    with pytest.raises(ValueError, match="Nope"):
        replace_section("# T\n\n## Cards\n\n- a\n", "Nope", "- b")


def test_replace_section_preserves_trailing_space_on_the_final_line() -> None:
    """OCR excerpts are cut at a fixed width and can legitimately end on a space.

    Stripping the body would silently alter the last card's excerpt whenever it
    happens to be the final entry in the section.
    """
    out = replace_section("# T\n\n## Cards\n\n- a\n", "Cards", "excerpt ending on ")

    assert "excerpt ending on \n" in out


# --------------------------------------------------------------------------
# Non-destructive regeneration
# --------------------------------------------------------------------------


def test_parse_existing_excerpts_recovers_published_text() -> None:
    doc = (
        "## Cards\n\n"
        "### aaaa1111bbbb2222 — First\n\n- Agency: X\n\nExcerpt (page 1):\n\nALPHA TEXT\n\n"
        "### cccc3333dddd4444 — Second\n\n- Agency: Y\n\nExcerpt (page 1):\n\nBETA TEXT\n"
    )

    assert parse_existing_excerpts(doc) == {
        "aaaa1111bbbb2222": "ALPHA TEXT",
        "cccc3333dddd4444": "BETA TEXT",
    }


def test_parse_existing_excerpts_skips_cards_without_one() -> None:
    doc = "## Cards\n\n### aaaa1111bbbb2222 — First\n\n- Agency: X\n\n### cccc3333dddd4444 — Second\n\n- Agency: Y\n"

    assert parse_existing_excerpts(doc) == {}


def test_resolve_excerpt_prefers_live_ocr() -> None:
    assert resolve_excerpt("aaaa1111bbbb2222", live="FRESH", published={"aaaa1111bbbb2222": "OLD"}) == "FRESH"


def test_resolve_excerpt_falls_back_to_published_when_ocr_is_unreachable() -> None:
    """A partially-mounted OCR tier must never delete already-published text.

    Image-only cards carry vision-pass text whose store may be absent on the
    machine running the generator; dropping it would silently shrink the
    published corpus description.
    """
    assert resolve_excerpt("aaaa1111bbbb2222", live=None, published={"aaaa1111bbbb2222": "OLD"}) == "OLD"


def test_resolve_excerpt_returns_none_when_neither_source_has_text() -> None:
    assert resolve_excerpt("aaaa1111bbbb2222", live=None, published={}) is None


# --------------------------------------------------------------------------
# Section intro
# --------------------------------------------------------------------------


def test_cards_intro_carries_the_live_count() -> None:
    """The intro hardcoded '334 cards', which is exactly the drift being fixed."""
    intro = build_cards_intro(card_count=412)

    assert "412 cards" in intro
    assert "334" not in intro


# --------------------------------------------------------------------------
# Provenance + freshness
# --------------------------------------------------------------------------


def test_provenance_line_round_trips() -> None:
    line = build_provenance_line(card_count=334, csv_sha256="13e730c18d6ea586")

    assert parse_provenance(f"# doc\n\n{line}\n\n## Cards\n") == (334, "13e730c18d6ea586")


def test_parse_provenance_returns_none_when_absent() -> None:
    assert parse_provenance("# doc\n\n## Cards\n") is None


def test_freshness_passes_when_counts_and_sha_agree() -> None:
    prov = build_provenance_line(card_count=2, csv_sha256="abc123")
    doc = f"# d\n\n{prov}\n\n## Cards\n"

    result = check_geo_freshness(
        card_count=2, csv_sha256="abc123", documents={"llms.txt": doc}
    )

    assert result == GeoFreshness(ok=True, problems=[])


def test_freshness_fails_on_card_count_drift() -> None:
    prov = build_provenance_line(card_count=294, csv_sha256="abc123")
    result = check_geo_freshness(
        card_count=334, csv_sha256="abc123", documents={"llms.txt": f"{prov}\n"}
    )

    assert not result.ok
    assert any("294" in p and "334" in p for p in result.problems)


def test_freshness_fails_on_manifest_sha_drift() -> None:
    """A re-promoted tranche can keep the count identical while bytes change."""
    prov = build_provenance_line(card_count=334, csv_sha256="48db08be3960")
    result = check_geo_freshness(
        card_count=334, csv_sha256="13e730c18d6e", documents={"llms.txt": f"{prov}\n"}
    )

    assert not result.ok
    assert any("sha" in p.lower() for p in result.problems)


def test_freshness_fails_when_provenance_is_missing_entirely() -> None:
    """An ungenerated file must not pass by having nothing to compare."""
    result = check_geo_freshness(
        card_count=334, csv_sha256="abc", documents={"llms.txt": "# doc\n\n## Cards\n"}
    )

    assert not result.ok
    assert any("provenance" in p.lower() for p in result.problems)


def test_freshness_reports_every_stale_document_not_just_the_first() -> None:
    stale = build_provenance_line(card_count=1, csv_sha256="old")
    result = check_geo_freshness(
        card_count=2,
        csv_sha256="new",
        documents={"llms.txt": stale, "llms-full.txt": stale},
    )

    assert not result.ok
    assert any("llms.txt" in p for p in result.problems)
    assert any("llms-full.txt" in p for p in result.problems)


# --------------------------------------------------------------------------
# Excerpt eligibility
# --------------------------------------------------------------------------


def test_already_published_excerpt_is_always_refreshed() -> None:
    assert should_include_excerpt(_card(asset_type="AUD"), already_published=True)


def test_new_pdf_card_may_gain_an_excerpt() -> None:
    assert should_include_excerpt(_card(asset_type="PDF"), already_published=False)


@pytest.mark.parametrize("asset_type", ["VID", "AUD", "IMG", None])
def test_new_non_pdf_card_never_gains_one(asset_type: str | None) -> None:
    """An A/V card's OCR directory holds its *paired* document's text.

    Emitting it would caption a Gemini 7 audio card with an Apollo 11
    debriefing — a factual error on a citable archive.
    """
    assert not should_include_excerpt(
        _card(asset_type=asset_type), already_published=False
    )


def test_parse_existing_excerpts_does_not_steal_a_later_cards_excerpt() -> None:
    """A card without an excerpt must not absorb the next card's.

    Under DOTALL a lazy `.*?` crosses `###` boundaries, which silently
    reattributes primary-source text to the wrong document.
    """
    doc = (
        "## Cards\n\n"
        "### aaaa1111bbbb2222 — No excerpt here\n\n- Agency: X\n\n"
        "### cccc3333dddd4444 — Has one\n\nExcerpt (page 1):\n\nBETA TEXT\n"
    )

    assert parse_existing_excerpts(doc) == {"cccc3333dddd4444": "BETA TEXT"}
