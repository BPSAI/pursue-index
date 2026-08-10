"""Tests for what a catalogue match is allowed to rest on (spec §6, PV1.5).

A catalogue match produces a dated ``previously_released`` claim against a named
artifact, so a match has to be the archive naming *this* document. Two
properties decide what counts as naming it:

* **What a path segment can name depends on the identifier.** A structured file
  number like ``62-HQ-83894`` means one thing wherever it appears, so an archive
  that gives it a directory of its own has named the document filed there — and
  the last directory segment is matched as well as the filename. A bare number
  means nothing on its own: archive paths number years, boxes and batches
  (``/2020/14/``), so for a purely-numeric identifier only the filename counts.
* **A bare number needs length to name anything.** "Case 14" or "NAID 413" are
  short enough to coincide with the incidental numerals in any filename, so
  below the floor a purely-numeric value resolves nothing.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from pursue_index.identifier_resolver import resolve_card
from pursue_index.identifiers import IdentifierKind
from pursue_index.provenance import DateBasis
from pursue_index.source_index import SourceEntry


def _entry(url: str, last_modified: str = "Mon, 01 Jun 2015 08:00:00 GMT") -> SourceEntry:
    return SourceEntry(
        url=url,
        filename=urlparse(url).path.rsplit("/", 1)[-1],
        last_modified=last_modified,
        agency="unknown",
        era="undated",
        era_year=None,
        date_basis=DateBasis.HTTP_LAST_MODIFIED,
    )


def test_short_blue_book_case_does_not_match_a_date_shaped_path_segment() -> None:
    """``/2020/14/`` is a path segment, not case 14."""
    card = {"card_id": "bb-14", "title": "Project Blue Book Case 14 summary", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/cia/2020/14/annual-budget-memo.pdf")]
    assert resolve_card(card, catalogue=catalogue) == []


def test_short_naid_does_not_match_a_number_inside_a_filename() -> None:
    """``NAID 413`` must not cite ``rpt-413.pdf``."""
    card = {"card_id": "naid-413", "title": "Record NAID 413 referenced in the file", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/fbi/reports/rpt-413.pdf")]
    assert resolve_card(card, catalogue=catalogue) == []


def test_a_long_enough_case_number_still_resolves_from_the_filename() -> None:
    """The floor removes short numbers, not the identifier family."""
    card = {"card_id": "bb-10073", "title": "Project Blue Book Case No. 10073 report", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/bluebook/case-10073.pdf")]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].identifier_kind == IdentifierKind.BLUE_BOOK_CASE.value


def test_a_structured_identifier_naming_the_last_directory_is_a_match() -> None:
    """An archive that gives a file number its own directory has still named it.

    ``.../fbi/62-hq-83894/cover-letter.pdf`` is one document out of the file the
    card cites, filed under the file number, with a name that describes the page
    rather than the case. The identifier is structured enough that a directory
    called ``62-hq-83894`` is the file number and nothing else, so the
    directory names the artifact as surely as the filename would.
    """
    card = {"card_id": "fbi-path", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    url = "https://documents.theblackvault.com/fbi/62-hq-83894/cover-letter.pdf"
    claims = resolve_card(card, catalogue=[_entry(url)])
    assert len(claims) == 1
    assert claims[0].artifact_url == url


def test_only_the_last_directory_segment_counts() -> None:
    """A segment further up names the collection the document sits in, not it.

    ``/62-hq-83894/1965/memo.pdf`` puts a year between the file number and the
    document, so the file number describes the shelf rather than the page — the
    document is one of many below it and is not the one the card cites.
    """
    card = {"card_id": "fbi-deep", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/fbi/62-hq-83894/1965/memo.pdf")]
    assert resolve_card(card, catalogue=catalogue) == []


def test_a_numeric_identifier_still_matches_on_the_filename_only() -> None:
    """A bare number in a directory is a shelf label, not the document's name.

    Archive paths number things freely — a year, a box, a batch — so a number
    standing alone as a directory says nothing about the document below it. Only
    a filename bearing the number names the document, which is what keeps a case
    number off an unrelated artifact that a directory happens to share digits
    with.
    """
    card = {"card_id": "bb-10073", "title": "Project Blue Book Case No. 10073 report", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/bluebook/10073/summary.pdf")]
    assert resolve_card(card, catalogue=catalogue) == []


def test_the_filename_extension_is_not_part_of_the_stem() -> None:
    """A match must survive stripping the suffix — and not be created by it."""
    card = {"card_id": "fbi-stem", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf")]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].artifact_url == "https://documents.theblackvault.com/fbi/62-hq-83894.pdf"


@pytest.mark.parametrize("value", ["14", "413", "1234"])
def test_purely_numeric_values_below_the_floor_resolve_nothing(value: str) -> None:
    card = {
        "card_id": f"naid-{value}",
        "title": f"Record NAID {value} in this file",
        "release_date": "5/8/26",
    }
    catalogue = [_entry(f"https://documents.theblackvault.com/fbi/{value}.pdf")]
    assert resolve_card(card, catalogue=catalogue) == []
