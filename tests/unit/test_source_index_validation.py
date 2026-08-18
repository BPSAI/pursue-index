"""Tests for catalogue-row validation at construction (spec §2/§6).

Every ``<loc>`` in a sitemap is a third-party string, and a catalogue row is one
hop upstream of a citation: the resolver turns a matched row's URL into a claim's
``artifact_url``. A row is only citable when its URL is an address a reader can
follow, so the row itself is the right place to establish that — the check then
holds for every path into the catalogue rather than for one of them.

The failure mode has to be a *drop*, not a raise: an enumeration over ~150k
third-party URLs meets rows of every shape, and one of them is worth one row —
never the whole build. The count of what was dropped is published so the
exclusion is auditable rather than silent.
"""

from __future__ import annotations

import pytest

from pursue_index.provenance import DateBasis
from pursue_index.sitemap_fetch import UrlRow
from pursue_index.source_index import (
    SourceEntry,
    build_catalogue,
    build_output,
    entries_from_rows,
    entry_from_url,
)

_NON_WEB = "javascript:alert(document.domain)"
_DATA_URL = "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="

#: A well-formed stored row, used as the control in every drop-and-count case.
_GOOD_ROW: dict[str, object] = {
    "url": "https://documents.theblackvault.com/fbi/a.pdf",
    "filename": "a.pdf",
    "last_modified": None,
    "agency": "fbi",
    "era": "undated",
    "era_year": None,
    "date_basis": DateBasis.SITEMAP_LASTMOD.value,
}


@pytest.mark.parametrize("url", [_NON_WEB, _DATA_URL, "ftp://example.gov/x.pdf", "not-a-url"])
def test_a_catalogue_row_refuses_a_non_web_url(url: str) -> None:
    with pytest.raises(ValueError):
        SourceEntry(
            url=url,
            filename="x.pdf",
            last_modified=None,
            agency="unknown",
            era="undated",
            era_year=None,
            date_basis=DateBasis.SITEMAP_LASTMOD,
        )


def test_entry_from_url_drops_a_non_web_url_instead_of_raising() -> None:
    assert entry_from_url(_NON_WEB, None) is None
    assert entry_from_url("https://documents.theblackvault.com/a/b.pdf", None) is not None


def test_build_catalogue_drops_and_counts_unusable_rows() -> None:
    rows = [
        UrlRow(loc="https://documents.theblackvault.com/fbi/a.pdf", lastmod=None),
        UrlRow(loc=_NON_WEB, lastmod=None),
        UrlRow(loc=_DATA_URL, lastmod=None),
    ]
    catalogue = build_catalogue(rows)
    assert [e.url for e in catalogue.entries] == ["https://documents.theblackvault.com/fbi/a.pdf"]
    assert catalogue.excluded_invalid_url == 2
    assert catalogue.total_urls == 3


def test_the_artifact_publishes_the_dropped_count() -> None:
    rows = [UrlRow(loc=_NON_WEB, lastmod=None)]
    output = build_output(build_catalogue(rows), "https://example.gov/robots.txt")
    assert output["invalid_urls_excluded"]["count"] == 1
    assert output["entry_count"] == 0


def test_deserialising_a_row_with_an_unusable_url_skips_it() -> None:
    """A stored artifact is an input too — one bad row must not kill the load."""
    bad = {**_GOOD_ROW, "url": _NON_WEB}
    entries, dropped = entries_from_rows([_GOOD_ROW, bad, _GOOD_ROW])
    assert [e.url for e in entries] == [_GOOD_ROW["url"], _GOOD_ROW["url"]]
    assert dropped == 1


@pytest.mark.parametrize("url", [None, 12, ["https://example.gov/a.pdf"]])
def test_a_row_whose_url_is_not_text_is_dropped_and_counted(url: object) -> None:
    """``url`` has to be a string before any URL rule can be applied to it.

    A stored row is JSON, so the field can hold any JSON type. Deciding "is this
    an http(s) URL?" is only meaningful for text, so a non-text value is settled
    the same way as an unusable URL: the row is dropped and counted.
    """
    entries, dropped = entries_from_rows([{**_GOOD_ROW, "url": url}, _GOOD_ROW])
    assert [e.url for e in entries] == [_GOOD_ROW["url"]]
    assert dropped == 1


@pytest.mark.parametrize("row", ["https://documents.theblackvault.com/fbi/a.pdf", ["a", "b"]])
def test_a_row_that_is_not_a_mapping_is_dropped_and_counted(row: object) -> None:
    """A catalogue row is a mapping of named fields; anything else is not a row.

    A bare string or a list carries no field names to read, so it yields no
    entry. The load keeps going: the artifact is enumerated over ~150k rows and
    a single ill-shaped one is worth exactly one row.
    """
    entries, dropped = entries_from_rows([row, _GOOD_ROW])
    assert [e.url for e in entries] == [_GOOD_ROW["url"]]
    assert dropped == 1


def test_the_load_completes_across_every_ill_shaped_row_at_once() -> None:
    """Mixed shapes in one artifact still yield the rows that are well-formed."""
    entries, dropped = entries_from_rows(
        [{"url": None}, {"url": 12}, "https://example.gov/a.pdf", ["a"], _GOOD_ROW]
    )
    assert [e.url for e in entries] == [_GOOD_ROW["url"]]
    assert dropped == 4
