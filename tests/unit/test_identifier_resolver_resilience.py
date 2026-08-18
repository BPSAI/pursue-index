"""Defence in depth: one unusable catalogue row costs one claim.

Catalogue rows are validated where they are built — at
:class:`~pursue_index.source_index.SourceEntry` — so in the ordinary course of a
run the resolver receives rows that are already known-good. These tests are the
layer beneath that: they fix what happens if a row ever reaches the resolver
without having passed the door, from a hand-edited artifact or from a future
producer with its own path into the catalogue.

The behaviour they pin is proportionality. Claim construction fails closed,
which is right — an unusable row must not become a claim. What it must also not
become is the end of the run: ``resolve_card`` is called once per card and
``classify`` calls it across the whole corpus, so a row that cannot produce an
honest claim costs exactly that claim, and the search moves on to the next row.
"""

from __future__ import annotations

from datetime import date

from pursue_index.identifier_resolver import resolve_card
from pursue_index.provenance import DateBasis
from pursue_index.source_index import SourceEntry

_LAST_MODIFIED = "Mon, 01 Jun 2015 08:00:00 GMT"


def _entry(url: str) -> SourceEntry:
    return SourceEntry(
        url=url,
        filename=url.rsplit("/", 1)[-1],
        last_modified=_LAST_MODIFIED,
        agency="unknown",
        era="undated",
        era_year=None,
        date_basis=DateBasis.HTTP_LAST_MODIFIED,
    )


def _unvalidated(entry: SourceEntry) -> SourceEntry:
    """A row carrying a URL the row constructor would have refused.

    Built by writing past the constructor, because the constructor is exactly
    what these tests are standing behind: this is the row that would exist if
    the outer layer were ever bypassed.
    """
    object.__setattr__(entry, "url", "javascript:alert(1)")
    return entry


def test_a_row_that_cannot_make_an_honest_claim_costs_only_that_claim() -> None:
    card = {"card_id": "fbi1", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    catalogue = [
        _unvalidated(_entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf")),
        _entry("https://documents.theblackvault.com/fbi/62-hq-83894-part2.pdf"),
    ]
    claims = resolve_card(card, catalogue=catalogue)
    assert [c.artifact_url for c in claims] == [
        "https://documents.theblackvault.com/fbi/62-hq-83894-part2.pdf"
    ]


def test_an_unusable_row_alone_yields_no_claim_rather_than_an_error() -> None:
    card = {"card_id": "fbi2", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    catalogue = [_unvalidated(_entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf"))]
    assert resolve_card(card, catalogue=catalogue) == []


def test_an_undatable_row_is_still_skipped_before_the_url_is_reached() -> None:
    """No ``Last-Modified`` means no honest date — unchanged behaviour."""
    entry = _entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf")
    undatable = SourceEntry(
        url=entry.url,
        filename=entry.filename,
        last_modified=None,
        agency=entry.agency,
        era=entry.era,
        era_year=entry.era_year,
        date_basis=entry.date_basis,
    )
    card = {"card_id": "fbi3", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    assert resolve_card(card, catalogue=[undatable]) == []


def test_a_valid_row_still_dates_its_claim() -> None:
    card = {"card_id": "fbi4", "title": "The 62-HQ-83894 case file records", "release_date": "5/8/26"}
    catalogue = [_entry("https://documents.theblackvault.com/fbi/62-hq-83894.pdf")]
    claims = resolve_card(card, catalogue=catalogue)
    assert len(claims) == 1
    assert claims[0].established_date == date(2015, 6, 1)
