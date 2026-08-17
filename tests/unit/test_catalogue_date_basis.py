"""What a catalogue row's date rests on, and how a claim reports it (spec §6d).

A catalogue row's date reaches the row by one of two routes, and the two are
written in different syntaxes. A sitemap ``<lastmod>`` element is ISO 8601
(``2020-05-30T09:12:00Z``); an HTTP ``Last-Modified`` response header is the
RFC 7231 date syntax (``Sat, 30 May 2020 09:12:00 GMT``). Neither is a
publication date — both say "existed on this host by" — so the distinction
these tests pin is not strength but *which evidence is in hand*:

* a row states the basis its own value rests on, and the value is read in that
  basis's syntax;
* the claim built from the row reports that same basis, so a reader of a claim
  always knows what they are reading;
* a value that is not written in the basis it states dates nothing at all,
  because a claim carries a date only when the date was read, never guessed.
"""

from __future__ import annotations

from datetime import date

import pytest

from pursue_index.identifier_resolver import resolve_card
from pursue_index.provenance import DateBasis
from pursue_index.source_index import SourceEntry

_URL = "https://documents.theblackvault.com/fbi/62-hq-83894.pdf"


def _card() -> dict:
    return {
        "card_id": "fbi-basis",
        "title": "The 62-HQ-83894 case file records",
        "release_date": "5/8/26",
    }


def _entry(last_modified: str | None, basis: DateBasis) -> SourceEntry:
    return SourceEntry(
        url=_URL,
        filename="62-hq-83894.pdf",
        last_modified=last_modified,
        agency="fbi",
        era="undated",
        era_year=None,
        date_basis=basis,
    )


def test_a_sitemap_lastmod_dates_a_claim_and_is_labelled_a_sitemap_date() -> None:
    """An ISO 8601 ``<lastmod>`` is the ordinary shape of a catalogue row."""
    entry = _entry("2020-05-30T09:12:00Z", DateBasis.SITEMAP_LASTMOD)
    claims = resolve_card(_card(), catalogue=[entry])
    assert len(claims) == 1
    assert claims[0].established_date == date(2020, 5, 30)
    assert claims[0].date_basis is DateBasis.SITEMAP_LASTMOD


def test_a_date_only_sitemap_lastmod_also_dates_a_claim() -> None:
    """``<lastmod>`` may carry a plain date; the sitemap standard allows both."""
    entry = _entry("2020-05-30", DateBasis.SITEMAP_LASTMOD)
    claims = resolve_card(_card(), catalogue=[entry])
    assert claims[0].established_date == date(2020, 5, 30)
    assert claims[0].date_basis is DateBasis.SITEMAP_LASTMOD


def test_a_response_header_date_is_read_and_labelled_as_a_header_date() -> None:
    """A value that came from a ``Last-Modified`` header keeps the header basis."""
    entry = _entry("Sat, 30 May 2020 09:12:00 GMT", DateBasis.HTTP_LAST_MODIFIED)
    claims = resolve_card(_card(), catalogue=[entry])
    assert len(claims) == 1
    assert claims[0].established_date == date(2020, 5, 30)
    assert claims[0].date_basis is DateBasis.HTTP_LAST_MODIFIED


@pytest.mark.parametrize(
    ("value", "basis"),
    [
        ("sometime in 2020", DateBasis.SITEMAP_LASTMOD),
        ("Sat, 30 May 2020 09:12:00 GMT", DateBasis.SITEMAP_LASTMOD),
        ("2020-05-30T09:12:00Z", DateBasis.HTTP_LAST_MODIFIED),
        (None, DateBasis.SITEMAP_LASTMOD),
    ],
)
def test_a_value_outside_its_stated_basis_yields_no_dated_claim(
    value: str | None, basis: DateBasis
) -> None:
    """A date is read in the syntax the row states, or the row dates nothing."""
    assert resolve_card(_card(), catalogue=[_entry(value, basis)]) == []
