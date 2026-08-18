"""Tests for identifier extraction and the false-NAID guard.

The load-bearing behaviour here is the *guard*: the ``255_`` / ``331_`` /
``341_`` prefixes in our card titles are record-group + box/folder finding-aid
locations, **not** National Archives Identifiers. Resolved as NAIDs against
NARA's catalog they return entirely unrelated records (``413270`` is "Travel to
the U.S. - GARIOA Students"), so a resolver that treats them as NAIDs emits
false citations on a citable archive. Every extractor here must refuse to hand a
record-group finding-aid number to NAID resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.identifiers import (
    Identifier,
    IdentifierKind,
    extract_blue_book,
    extract_crest,
    extract_fbi_files,
    extract_identifiers,
    extract_naids,
    is_rg_finding_aid_token,
    rg_finding_aid_numbers,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _cards() -> list[dict]:
    return json.loads(_MANIFEST.read_text())["cards"]


def _card_by_title(fragment: str) -> dict:
    for card in _cards():
        if fragment in (card.get("title") or ""):
            return card
    raise AssertionError(f"no card whose title contains {fragment!r}")


# --------------------------------------------------------------------------
# The guard: record-group finding-aid numbers are never NAIDs.
# --------------------------------------------------------------------------

# The three known false positives, from real card titles. Each is
# ``<record-group>_<box/folder>_...`` — the box/folder number must never be
# handed to NAID resolution.
_RG_FALSE_POSITIVES = {
    "255": ("255_413270_UFO's_and_Defense_What_Should_we_Prepare_For", "413270"),
    "331": ("331_120752_Numeric_Files_1944-1945_37153_German_Armament", "120752"),
    "341": ("341_110448_Records_Relating_to_the_Collection", "110448"),
}


def test_rg_prefixed_number_is_flagged_as_finding_aid() -> None:
    for _rg, (title, number) in _RG_FALSE_POSITIVES.items():
        assert is_rg_finding_aid_token(title)
        assert number in rg_finding_aid_numbers(title)


def test_255_413270_is_never_extracted_as_a_naid() -> None:
    # The GARIOA collision: 413270 resolved as a NAID is an unrelated record.
    title = _RG_FALSE_POSITIVES["255"][0]
    assert extract_naids(title) == []


def test_331_120752_is_never_extracted_as_a_naid() -> None:
    title = _RG_FALSE_POSITIVES["331"][0]
    assert extract_naids(title) == []


def test_341_110448_is_never_extracted_as_a_naid() -> None:
    title = _RG_FALSE_POSITIVES["341"][0]
    assert extract_naids(title) == []


def test_guard_refuses_even_when_naid_context_word_is_present() -> None:
    # Belt and suspenders: a hostile string that puts the finding-aid number in
    # an explicit NAID context must still be refused, because the same number
    # also appears as a record-group finding-aid location.
    hostile = "National Archives Identifier 413270 for 255_413270_UFO's_and_Defense"
    assert extract_naids(hostile) == []


def test_the_three_rg_cards_yield_no_naid_identifier() -> None:
    for _rg, (title_fragment, _num) in _RG_FALSE_POSITIVES.items():
        prefix = title_fragment.split("_")[0]
        card = _card_by_title(f"{prefix}_")
        idents = extract_identifiers(card)
        assert all(i.kind is not IdentifierKind.NAID for i in idents), card["title"]


# --------------------------------------------------------------------------
# Genuine NAIDs *are* extracted — the guard is precise, not blanket.
# --------------------------------------------------------------------------


def test_genuine_naid_in_context_is_extracted() -> None:
    idents = extract_naids("See NAID 12345678 in the National Archives catalog.")
    assert idents == [Identifier(kind=IdentifierKind.NAID, value="12345678", raw="12345678")]


def test_genuine_naid_from_catalog_url_is_extracted() -> None:
    idents = extract_naids("https://catalog.archives.gov/id/305236 has the record.")
    assert [i.value for i in idents] == ["305236"]


def test_bare_number_without_naid_context_is_not_a_naid() -> None:
    # A lone number with no NAID context word is not a NAID — precision, not recall.
    assert extract_naids("The file spans 305236 pages of testimony.") == []


# --------------------------------------------------------------------------
# FBI file / serial numbers.
# --------------------------------------------------------------------------


def test_fbi_file_number_is_extracted() -> None:
    idents = extract_fbi_files("The FBI's 62-HQ-83894 case file includes records.")
    assert idents == [Identifier(kind=IdentifierKind.FBI_FILE, value="62-HQ-83894", raw="62-HQ-83894")]


def test_fbi_serial_suffix_is_kept() -> None:
    idents = extract_fbi_files("document 62-HQ-83894-42 was withheld")
    assert idents[0].value == "62-HQ-83894-42"


def test_every_fbi_62hq_card_extracts_the_file_number() -> None:
    fbi = [c for c in _cards() if "62-HQ-83894" in (c.get("title") or "")]
    assert len(fbi) >= 18
    for card in fbi:
        idents = extract_identifiers(card)
        assert any(
            i.kind is IdentifierKind.FBI_FILE and i.value.startswith("62-HQ-83894") for i in idents
        ), card["title"]


# --------------------------------------------------------------------------
# CIA CREST identifiers.
# --------------------------------------------------------------------------


def test_cia_crest_identifier_is_extracted() -> None:
    idents = extract_crest("Document CIA-RDP79B00752A000300070001-6 was released.")
    assert idents[0].kind is IdentifierKind.CIA_CREST
    assert idents[0].value == "CIA-RDP79B00752A000300070001-6"


def test_non_crest_cia_prefix_is_not_a_crest_id() -> None:
    # CIA-UAP-015 is our own card label, not a CREST RDP identifier.
    assert extract_crest("CIA-UAP-015, Project Blue Book Special Report No. 14") == []


# --------------------------------------------------------------------------
# Project Blue Book case numbers.
# --------------------------------------------------------------------------


def test_blue_book_case_number_is_extracted() -> None:
    idents = extract_blue_book("Project Blue Book Case No. 10073 details a sighting.")
    assert idents[0].kind is IdentifierKind.BLUE_BOOK_CASE
    assert idents[0].value == "10073"


def test_blue_book_mention_without_case_number_yields_nothing() -> None:
    # A named mention with no case number is not an identifier to resolve.
    assert extract_blue_book("This is the USAF Project Blue Book with a CIA cover sheet.") == []


# --------------------------------------------------------------------------
# Identifier dataclass guards + dedup.
# --------------------------------------------------------------------------


def test_extract_identifiers_deduplicates() -> None:
    card = {
        "card_id": "x",
        "title": "62-HQ-83894 file",
        "description": "The 62-HQ-83894 case file, see 62-HQ-83894 again.",
        "asset_filename": "62-hq-83894.pdf",
    }
    values = [(i.kind, i.value) for i in extract_identifiers(card)]
    assert len(values) == len(set(values))


def test_crest_pattern_does_not_backtrack_quadratically() -> None:
    """Extraction stays linear on a long non-matching run.

    The input is a whole CSV description or title, so the pattern must not pair
    adjacent unbounded quantifiers over one character class: that shape costs
    seconds on a few kilobytes that never match.
    """
    import time

    from pursue_index.identifiers import extract_identifiers

    hostile = {"description": "CIA-RDP" + ("A" * 20000) + "_"}
    start = time.perf_counter()
    extract_identifiers(hostile)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"pathological backtracking: {elapsed:.2f}s"
