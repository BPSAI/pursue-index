"""Tests for the courteous sitemap fetcher + XML parsing.

The fetcher's whole discipline is captured here: it fetches *listings only*
(``robots.txt`` and sitemap ``.xml`` — never a PDF or any other asset), it
spaces requests out sequentially, and on any non-2xx it **aborts with a clear
message** rather than retrying in a loop. The parsers turn the published
``robots.txt`` and the sitemap XML into plain URL/last-modified rows without
resolving any external entity.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest

from pursue_index import sitemap_fetch
from pursue_index.sitemap_fetch import (
    DEFAULT_ROBOTS_URL,
    CourteousFetcher,
    SitemapFetchError,
    is_listing_url,
    parse_robots_sitemaps,
    parse_sitemap_index,
    parse_url_entries,
)


class _Resp(NamedTuple):
    """A minimal stand-in for an HTTP response (httpx-shaped)."""

    status_code: int
    text: str
    headers: dict[str, str]


class _Recorder:
    """A fake ``get`` + ``sleep`` pair that records how it was called."""

    def __init__(self, responses: dict[str, _Resp]) -> None:
        self._responses = responses
        self.fetched: list[str] = []
        self.slept: list[float] = []

    def get(self, url: str) -> _Resp:
        self.fetched.append(url)
        return self._responses[url]

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://documents3.theblackvault.com/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""

_URLSET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://documents3.theblackvault.com/cbp/report.pdf</loc>
    <lastmod>2020-05-30T09:12:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://documents3.theblackvault.com/cia/ufos/nodate.pdf</loc>
  </url>
</urlset>"""


# --------------------------------------------------------------------------
# is_listing_url — the structural "no PDFs" guard.
# --------------------------------------------------------------------------


def test_robots_and_xml_are_listings() -> None:
    assert is_listing_url("https://host/robots.txt")
    assert is_listing_url("https://host/sitemap-1.xml")
    assert is_listing_url("https://host/path/sitemap.xml?x=1")


@pytest.mark.parametrize(
    "url",
    [
        "https://host/cbp/report.pdf",
        "https://host/a/scan.PDF",
        "https://host/image.jpg",
        "https://host/clip.mp4",
        "https://host/folder/",
    ],
)
def test_assets_are_not_listings(url: str) -> None:
    assert not is_listing_url(url)


# --------------------------------------------------------------------------
# CourteousFetcher — rate-limited, sequential, aborts on non-2xx, no PDFs.
# --------------------------------------------------------------------------


def test_fetch_returns_body_and_last_modified() -> None:
    url = "https://host/sitemap.xml"
    rec = _Recorder({url: _Resp(200, _URLSET_XML, {"Last-Modified": "Sat, 30 May 2020 09:12:00 GMT"})})
    fetcher = CourteousFetcher(get=rec.get, sleep=rec.sleep, delay=1.0)

    listing = fetcher.fetch(url)

    assert listing.url == url
    assert listing.body == _URLSET_XML
    assert listing.last_modified == "Sat, 30 May 2020 09:12:00 GMT"


def test_fetch_is_rate_limited_between_sequential_requests() -> None:
    a, b = "https://host/a.xml", "https://host/b.xml"
    rec = _Recorder({a: _Resp(200, "<a/>", {}), b: _Resp(200, "<b/>", {})})
    fetcher = CourteousFetcher(get=rec.get, sleep=rec.sleep, delay=1.5)

    fetcher.fetch(a)
    fetcher.fetch(b)

    # Sequential politeness: one delay per request, at the configured spacing.
    assert rec.slept == [1.5, 1.5]
    assert rec.fetched == [a, b]


def test_non_2xx_aborts_with_clear_message_and_does_not_retry() -> None:
    url = "https://host/sitemap.xml"
    rec = _Recorder({url: _Resp(429, "slow down", {})})
    fetcher = CourteousFetcher(get=rec.get, sleep=rec.sleep, delay=0.0)

    with pytest.raises(SitemapFetchError) as excinfo:
        fetcher.fetch(url)

    message = str(excinfo.value)
    assert "429" in message
    assert url in message
    # Aborted, not retried: exactly one request was made.
    assert rec.fetched == [url]


def test_fetch_refuses_non_listing_urls_so_no_pdf_is_downloaded() -> None:
    url = "https://host/cbp/report.pdf"
    rec = _Recorder({url: _Resp(200, "%PDF-1.7", {})})
    fetcher = CourteousFetcher(get=rec.get, sleep=rec.sleep, delay=0.0)

    with pytest.raises(SitemapFetchError) as excinfo:
        fetcher.fetch(url)

    assert "listing" in str(excinfo.value).lower()
    # The refusal happens before any network call — nothing was fetched.
    assert rec.fetched == []


def test_default_robots_url_targets_the_leaked_enumeration_path() -> None:
    assert DEFAULT_ROBOTS_URL == "https://documents3.theblackvault.com/robots.txt"


# --------------------------------------------------------------------------
# Parsers.
# --------------------------------------------------------------------------


def test_parse_robots_extracts_sitemap_lines() -> None:
    robots = (
        "User-agent: *\n"
        "Disallow: /private/\n"
        "Sitemap: https://host/sitemap-index-1.xml\n"
        "sitemap: https://host/sitemap-index-2.xml\n"
        "\n"
    )
    assert parse_robots_sitemaps(robots) == [
        "https://host/sitemap-index-1.xml",
        "https://host/sitemap-index-2.xml",
    ]


def test_parse_sitemap_index_returns_child_sitemaps() -> None:
    assert parse_sitemap_index(_INDEX_XML) == [
        "https://documents3.theblackvault.com/sitemap-1.xml",
    ]


def test_parse_url_entries_reads_loc_and_optional_lastmod() -> None:
    entries = parse_url_entries(_URLSET_XML)
    assert [e.loc for e in entries] == [
        "https://documents3.theblackvault.com/cbp/report.pdf",
        "https://documents3.theblackvault.com/cia/ufos/nodate.pdf",
    ]
    assert entries[0].lastmod == "2020-05-30T09:12:00+00:00"
    assert entries[1].lastmod is None


def test_xml_with_a_doctype_is_rejected_not_expanded() -> None:
    # A sitemap never carries a DTD; refusing one neutralises entity-expansion.
    hostile = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE urlset [<!ENTITY x "boom">]>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    with pytest.raises(SitemapFetchError):
        parse_url_entries(hostile)


# --- declaration handling across the whole prolog ---------------------------


def test_dtd_hidden_behind_a_long_comment_is_still_refused() -> None:
    """A doctype is refused wherever it sits in the prolog.

    A well-formed XML prolog may carry arbitrarily long comments ahead of
    `<!DOCTYPE>`, so the check reads the whole prolog rather than a fixed
    leading window — the module promises no entity expansion, and that promise
    cannot depend on where the declaration happens to fall.
    """
    hidden = (
        '<?xml version="1.0"?>\n'
        + "<!-- " + ("A" * 4096) + " -->\n"
        + '<!DOCTYPE lol [<!ENTITY a "boom">]>\n'
        + "<urlset><url><loc>https://example.test/x</loc></url></urlset>"
    )

    with pytest.raises(sitemap_fetch.SitemapFetchError, match="DTD"):
        sitemap_fetch._parse_xml(hidden)


def test_entity_declaration_anywhere_is_refused() -> None:
    payload = "<urlset>" + ("<!-- pad -->" * 500) + '<!ENTITY x "y">' + "</urlset>"

    with pytest.raises(sitemap_fetch.SitemapFetchError, match="DTD"):
        sitemap_fetch._parse_xml(payload)


def test_a_clean_sitemap_still_parses() -> None:
    clean = (
        '<?xml version="1.0"?>\n<!-- ordinary comment -->\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.test/a.pdf</loc></url></urlset>"
    )

    assert sitemap_fetch._parse_xml(clean) is not None
