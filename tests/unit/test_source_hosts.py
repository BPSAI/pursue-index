"""Pinned source-host allowlist and plain-text sitemaps for the source index.

Fixture-driven: no socket, no real waiting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

import pytest

from pursue_index.sitemap_fetch import (
    CourteousFetcher,
    SitemapFetchError,
    is_listing_url,
    parse_text_sitemap,
)
from pursue_index.source_index import (
    SOURCE_HOSTS_PATH,
    build_catalogue_from_fetcher,
    load_source_hosts,
)

_REPO = Path(__file__).resolve().parents[2]
_HOSTS = frozenset(
    {
        "documents3.theblackvault.com",
        "www.theblackvault.com",
        "documents.theblackvault.com",
        "documents2.theblackvault.com",
    }
)
_ROBOTS_URL = "https://documents3.theblackvault.com/robots.txt"
_ROBOTS = """User-agent: *
Sitemap: https://www.theblackvault.com/documentarchive/sitemap_index.xml
Sitemap: https://www.theblackvault.com/casefiles/sitemap_index.xml
Sitemap: https://www.theblackvault.com/sitemap-www-documents.txt
Sitemap: https://documents.theblackvault.com/sitemap3.txt
Sitemap: https://documents.theblackvault.com/sitemap2.txt
Sitemap: https://documents.theblackvault.com/sitemap.txt
Sitemap: https://documents2.theblackvault.com/sitemap.txt
"""


def _index(*locs: str) -> str:
    body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'


def _urlset(*locs: str) -> str:
    body = "".join(f"<url><loc>{loc}</loc><lastmod>2020-05-30</lastmod></url>" for loc in locs)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


class _Resp(NamedTuple):
    status_code: int
    text: str
    headers: dict[str, str]


class _Net:
    """Fake ``get``: fails the test on any non-listing URL; records order."""

    def __init__(self, pages: dict[str, str], statuses: dict[str, int] | None = None) -> None:
        self.pages = pages
        self.statuses = statuses or {}
        self.requested: list[str] = []
        self.sleeps: list[float] = []
        self.events: list[str] = []

    def get(self, url: str) -> _Resp:
        path = url.split("?")[0].lower()
        assert path.endswith((".xml", ".txt")), f"asset fetched: {url}"
        self.requested.append(url)
        self.events.append("get")
        return _Resp(self.statuses.get(url, 200), self.pages.get(url, ""), {})

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.events.append("sleep")


def _build(net: _Net, robots_url: str = _ROBOTS_URL, hosts: frozenset[str] = _HOSTS, delay: float = 0.0):
    fetcher = CourteousFetcher(get=net.get, sleep=net.sleep, delay=delay)
    return build_catalogue_from_fetcher(fetcher, robots_url, allowed_hosts=hosts)


def _full_pages() -> dict[str, str]:
    return {
        _ROBOTS_URL: _ROBOTS,
        "https://www.theblackvault.com/documentarchive/sitemap_index.xml": _index(
            "https://www.theblackvault.com/documentarchive/child.xml"
        ),
        "https://www.theblackvault.com/documentarchive/child.xml": _urlset("https://www.theblackvault.com/a/cia/1.pdf"),
        "https://www.theblackvault.com/casefiles/sitemap_index.xml": _index(),
        "https://www.theblackvault.com/sitemap-www-documents.txt": "https://www.theblackvault.com/b/fbi/2.pdf\n",
        "https://documents.theblackvault.com/sitemap3.txt": "https://documents.theblackvault.com/c/3.pdf\n",
        "https://documents.theblackvault.com/sitemap2.txt": "https://documents.theblackvault.com/c/4.pdf\n",
        "https://documents.theblackvault.com/sitemap.txt": "https://documents.theblackvault.com/c/5.pdf\n",
        "https://documents2.theblackvault.com/sitemap.txt": "https://documents2.theblackvault.com/d/6.pdf\n",
    }


# -- config ---------------------------------------------------------------


def test_config_file_loads_the_four_hosts() -> None:
    assert load_source_hosts(_REPO / SOURCE_HOSTS_PATH) == _HOSTS


@pytest.mark.parametrize("content", [None, "{}", '{"hosts": []}', '{"hosts": "x"}', "not json", '{"hosts": [1]}'])
def test_missing_or_empty_config_refuses(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "hosts.json"
    if content is not None:
        path.write_text(content)
    with pytest.raises(SitemapFetchError):
        load_source_hosts(path)


def test_config_hosts_are_normalised(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps({"hosts": ["WWW.Example.COM."]}))
    assert load_source_hosts(path) == frozenset({"www.example.com"})


# -- allowlist ------------------------------------------------------------


def test_every_listed_host_is_followed() -> None:
    net = _Net(_full_pages())
    catalogue = _build(net)
    assert set(net.requested) == set(_full_pages())
    assert len(catalogue.entries) == 6


@pytest.mark.parametrize(
    "robots_url",
    [
        "https://x.theblackvault.com/robots.txt",
        "https://theblackvault.com.evil.example/robots.txt",
        "https://evil.theblackvault.com.example/robots.txt",
        "http://documents3.theblackvault.com/robots.txt",
        "ftp://documents3.theblackvault.com/robots.txt",
    ],
)
def test_off_list_robots_url_is_refused_before_any_request(robots_url: str) -> None:
    net = _Net({})
    with pytest.raises(SitemapFetchError):
        _build(net, robots_url=robots_url)
    assert net.requested == []


@pytest.mark.parametrize(
    "robots_url",
    ["https://DOCUMENTS3.TheBlackVault.com/robots.txt", "https://documents3.theblackvault.com./robots.txt"],
)
def test_uppercase_and_trailing_dot_forms_are_allowed(robots_url: str) -> None:
    net = _Net({robots_url: ""})
    _build(net, robots_url=robots_url)
    assert net.requested == [robots_url]


_BAD = [
    "https://x.theblackvault.com/{}",
    "https://theblackvault.com.evil.example/{}",
    "http://www.theblackvault.com/{}",
]


@pytest.mark.parametrize("bad", _BAD)
def test_off_list_sitemap_index_is_skipped_with_note(bad: str, capsys: pytest.CaptureFixture[str]) -> None:
    url = bad.format("sitemap_index.xml")
    net = _Net({_ROBOTS_URL: f"Sitemap: {url}\n"})
    _build(net)
    assert net.requested == [_ROBOTS_URL]
    assert "skip" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("bad", _BAD)
def test_off_list_child_sitemap_is_never_fetched(bad: str) -> None:
    child = bad.format("child.xml")
    idx = "https://www.theblackvault.com/i.xml"
    net = _Net({_ROBOTS_URL: f"Sitemap: {idx}\n", idx: _index(child)})
    _build(net)
    assert net.requested == [_ROBOTS_URL, idx]


@pytest.mark.parametrize("bad", _BAD)
def test_off_list_text_sitemap_is_never_fetched(bad: str) -> None:
    txt = bad.format("sitemap.txt")
    net = _Net({_ROBOTS_URL: f"Sitemap: {txt}\n"})
    _build(net)
    assert net.requested == [_ROBOTS_URL]


def test_child_of_an_index_must_be_xml_even_on_an_allowed_host() -> None:
    idx = "https://www.theblackvault.com/i.xml"
    txt = "https://www.theblackvault.com/sitemap.txt"
    net = _Net({_ROBOTS_URL: f"Sitemap: {idx}\n", idx: _index(txt)})
    _build(net)
    assert txt not in net.requested


# -- text sitemaps --------------------------------------------------------


def test_parse_text_sitemap_rows_blank_lines_and_dropped() -> None:
    text = "  https://h/a.pdf  \n\n\r\nhttp://h/b.pdf\nftp://h/c.pdf\njavascript:x\nnot a url\n"
    rows, dropped = parse_text_sitemap(text)
    assert [(r.loc, r.lastmod) for r in rows] == [("https://h/a.pdf", None), ("http://h/b.pdf", None)]
    assert dropped == 3


def test_text_sitemap_dropped_lines_are_counted_in_the_catalogue() -> None:
    txt = "https://documents.theblackvault.com/sitemap.txt"
    net = _Net({_ROBOTS_URL: f"Sitemap: {txt}\n", txt: "https://documents.theblackvault.com/a.pdf\nftp://x/y\n"})
    cat = _build(net)
    assert [e.last_modified for e in cat.entries] == [None]
    assert cat.excluded_invalid_url == 1


def test_unlisted_txt_is_never_fetched() -> None:
    idx = "https://www.theblackvault.com/i.xml"
    other = "https://www.theblackvault.com/other.txt"
    net = _Net({_ROBOTS_URL: f"Sitemap: {idx}\n", idx: _index(other)})
    _build(net)
    assert other not in net.requested


def test_is_listing_url_does_not_admit_arbitrary_txt() -> None:
    assert not is_listing_url("https://www.theblackvault.com/sitemap.txt")


def test_fetcher_refuses_unlisted_txt_before_request() -> None:
    net = _Net({})
    fetcher = CourteousFetcher(get=net.get, sleep=net.sleep, delay=0.0)
    with pytest.raises(SitemapFetchError):
        fetcher.fetch("https://www.theblackvault.com/sitemap.txt")
    assert net.requested == []


# -- assets, status, spacing ---------------------------------------------


def test_no_asset_url_is_ever_fetched() -> None:
    net = _Net(_full_pages())  # _Net.get fails on any non-listing URL
    _build(net)
    assert all(u.endswith((".xml", ".txt")) for u in net.requested)


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_status_aborts_with_no_further_requests(status: int) -> None:
    pages = _full_pages()
    first = "https://www.theblackvault.com/documentarchive/sitemap_index.xml"
    net = _Net(pages, statuses={first: status})
    with pytest.raises(SitemapFetchError, match=str(status)):
        _build(net)
    assert net.requested == [_ROBOTS_URL, first]


def test_sleep_precedes_every_request_with_the_courtesy_delay() -> None:
    net = _Net(_full_pages())
    _build(net, delay=1.0)
    assert net.sleeps == [1.0] * len(net.requested)
    assert net.events == ["sleep", "get"] * len(net.requested)
