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


# --------------------------------------------------------------------------
# One redirect hop — https, pinned host, listing target; anything else refused.
# --------------------------------------------------------------------------

_OLD = "https://www.theblackvault.com/documentarchive/sitemap_index.xml"
_NEW = "https://www.theblackvault.com/documentarchive/sitemap.xml"
_HOSTS = ("www.theblackvault.com", "documents.theblackvault.com")


def _redirect(location: str | None, status: int = 302) -> _Resp:
    return _Resp(status, "", {} if location is None else {"Location": location})


def _hop_fetcher(responses: dict[str, _Resp]) -> tuple[CourteousFetcher, _Recorder, list[str]]:
    events: list[str] = []
    rec = _Recorder(responses)
    fetcher = CourteousFetcher(
        get=lambda u: (events.append(f"get {u}"), rec.get(u))[1],
        sleep=lambda s: events.append("sleep"),
        allowed_hosts=_HOSTS,
    )
    return fetcher, rec, events


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_same_host_redirect_is_followed_once(status: int) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(_NEW, status), _NEW: _Resp(200, _INDEX_XML, {})})
    result = fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD, _NEW]
    assert result.body == _INDEX_XML
    assert result.url == _NEW
    assert fetcher.redirects_followed == 1
    assert fetcher.redirects_refused == 0
    assert fetcher.requests == 2


def test_relative_location_resolves_against_request_url() -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect("/documentarchive/sitemap.xml"), _NEW: _Resp(200, "ok", {})})
    assert fetcher.fetch(_OLD).body == "ok"
    assert rec.fetched == [_OLD, _NEW]


def test_redirect_to_other_listed_host_is_followed() -> None:
    target = "https://documents.theblackvault.com/sitemap.xml"
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(target), target: _Resp(200, "ok", {})})
    assert fetcher.fetch(_OLD).body == "ok"
    assert rec.fetched == [_OLD, target]
    assert fetcher.redirects_followed == 1


def test_hop_is_paced_by_the_courtesy_delay() -> None:
    fetcher, _, events = _hop_fetcher({_OLD: _redirect(_NEW), _NEW: _Resp(200, "ok", {})})
    fetcher.fetch(_OLD)
    assert events == ["sleep", f"get {_OLD}", "sleep", f"get {_NEW}"]


def test_hop_is_logged_with_both_urls(capsys: pytest.CaptureFixture[str]) -> None:
    fetcher, _, _ = _hop_fetcher({_OLD: _redirect(_NEW), _NEW: _Resp(200, "ok", {})})
    fetcher.fetch(_OLD)
    out = capsys.readouterr().out
    assert _OLD in out and _NEW in out


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/sitemap.xml",
        "https://www.theblackvault.com.evil.example/sitemap.xml",
        "http://www.theblackvault.com/documentarchive/sitemap.xml",
        "https://www.theblackvault.com/files/report.pdf",
        "",
        None,
    ],
)
def test_unsafe_redirect_is_refused_without_a_request(location: str | None) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(location)})
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD]
    assert fetcher.redirects_refused == 1
    assert fetcher.redirects_followed == 0


class _MultiHeaders(dict):  # type: ignore[type-arg]
    """httpx-shaped headers: ``items`` joins repeats, ``get_list`` keeps each one."""

    def __init__(self, locations: list[str]) -> None:
        super().__init__({"Location": ", ".join(locations)})
        self._locations = locations

    def get_list(self, key: str) -> list[str]:
        return list(self._locations) if key.lower() == "location" else []


@pytest.mark.parametrize(
    "location",
    [
        "https://www.theblackvault.com:8443/documentarchive/sitemap.xml",
        "https://www.theblackvault.com:80/documentarchive/sitemap.xml",
        "https://www.theblackvault.com:abc/documentarchive/sitemap.xml",
        "https://www.theblackvault.com:99999/documentarchive/sitemap.xml",
    ],
)
def test_redirect_to_a_non_default_port_is_refused(location: str) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(location), location: _Resp(200, "ok", {})})
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD]
    assert fetcher.redirects_refused == 1
    assert fetcher.redirects_followed == 0


@pytest.mark.parametrize("location", [_NEW, "https://www.theblackvault.com:443/documentarchive/sitemap.xml"])
def test_redirect_with_no_port_or_the_default_port_is_followed(location: str) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(location), location: _Resp(200, "ok", {})})
    assert fetcher.fetch(_OLD).body == "ok"
    assert rec.fetched == [_OLD, location]
    assert fetcher.redirects_followed == 1


def test_duplicate_location_headers_are_refused_without_a_request() -> None:
    first, second = _NEW, "https://documents.theblackvault.com/sitemap.xml"
    response = _Resp(302, "", _MultiHeaders([first, second]))
    joined = response.headers["Location"]
    fetcher, rec, _ = _hop_fetcher(
        {_OLD: response, first: _Resp(200, "ok", {}), second: _Resp(200, "ok", {}), joined: _Resp(200, "ok", {})}
    )
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD]
    assert fetcher.redirects_refused == 1
    assert fetcher.redirects_followed == 0


def test_second_hop_is_refused() -> None:
    third = "https://www.theblackvault.com/documentarchive/other.xml"
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(_NEW), _NEW: _redirect(third)})
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD, _NEW]
    assert fetcher.redirects_followed == 1
    assert fetcher.redirects_refused == 1


def test_redirect_without_allowlist_is_refused() -> None:
    rec = _Recorder({_OLD: _redirect(_NEW)})
    fetcher = CourteousFetcher(get=rec.get, sleep=rec.sleep)
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert fetcher.redirects_refused == 1


def test_text_sitemap_redirect_target_must_be_declared() -> None:
    old, new = "https://www.theblackvault.com/a.txt", "https://www.theblackvault.com/b.txt"
    fetcher, rec, _ = _hop_fetcher({old: _redirect(new), new: _Resp(200, "ok", {})})
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(old, declared={old})
    assert rec.fetched == [old]
    fetcher, rec, _ = _hop_fetcher({old: _redirect(new), new: _Resp(200, "ok", {})})
    assert fetcher.fetch(old, declared={old, new}).body == "ok"


@pytest.mark.parametrize("status", [403, 429, 500])
def test_non_redirect_errors_still_abort(status: int) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _Resp(status, "", {})})
    with pytest.raises(SitemapFetchError, match=str(status)):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD]
    assert fetcher.redirects_refused == 0


def test_hop_target_403_aborts() -> None:
    fetcher, _, _ = _hop_fetcher({_OLD: _redirect(_NEW), _NEW: _Resp(403, "", {})})
    with pytest.raises(SitemapFetchError, match="403"):
        fetcher.fetch(_OLD)


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example\\@www.theblackvault.com/s.xml",
        "https://www.theblackvault.com@evil.example/s.xml",
        "https://user:pw@www.theblackvault.com/s.xml",
        "https://www.theblackvault.com/ s.xml",
        "https://www.theblackvault.com/s.xml\r\n",
        "https://wwẉ.theblackvault.com/s.xml",
    ],
)
def test_location_that_parsers_could_read_differently_is_refused(location: str) -> None:
    fetcher, rec, _ = _hop_fetcher({_OLD: _redirect(location), location: _Resp(200, "ok", {}), location.strip(): _Resp(200, "ok", {})})
    with pytest.raises(SitemapFetchError, match="redirect"):
        fetcher.fetch(_OLD)
    assert rec.fetched == [_OLD]
    assert fetcher.redirects_refused == 1
    assert fetcher.redirects_followed == 0
