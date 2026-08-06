"""Courteous sitemap fetcher + XML parsing (PV1.4).

The source catalogue is enumerated from the sitemap indexes leaked via
``documents3.theblackvault.com/robots.txt``. This module is the only thing that
touches the network, and it is deliberately narrow:

* **Listings only, never an asset.** :func:`is_listing_url` admits ``robots.txt``
  and sitemap ``.xml`` and nothing else; :meth:`CourteousFetcher.fetch` refuses
  anything else *before* making a request. Structurally, no PDF (or image, zip,
  video…) can be downloaded through this fetcher — the ``<loc>`` asset URLs in a
  sitemap are recorded by the catalogue, never fetched.
* **Sequential and rate-limited.** One request at a time, spaced by a courtesy
  ``delay`` (~1 s) so the host is never hammered.
* **Abort, don't retry.** On any non-2xx the fetcher raises
  :class:`SitemapFetchError` with a clear message naming the status and URL —
  there is no retry loop that would keep pounding a host that is rate-limiting us.

The parsers turn ``robots.txt`` and sitemap XML into plain rows. XML is parsed
with a DTD refused up front, so a hostile listing cannot trigger entity
expansion.

The ``get``/``sleep`` callables are injected so the whole thing is exercised in
tests against fixture bytes, with no live network call.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NamedTuple, Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

__all__ = [
    "DEFAULT_DELAY_SECONDS",
    "DEFAULT_ROBOTS_URL",
    "CourteousFetcher",
    "FetchedListing",
    "SitemapFetchError",
    "UrlRow",
    "is_listing_url",
    "parse_robots_sitemaps",
    "parse_sitemap_index",
    "parse_url_entries",
]

#: The leaked enumeration path (spec §2b): robots.txt exposes four sitemap indexes.
DEFAULT_ROBOTS_URL = "https://documents3.theblackvault.com/robots.txt"

#: Courtesy spacing between sequential requests, in seconds.
DEFAULT_DELAY_SECONDS = 1.0

_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class SitemapFetchError(RuntimeError):
    """A fetch was refused, aborted on a non-2xx, or a listing was malformed."""


class FetchedListing(NamedTuple):
    """A successfully fetched listing (robots.txt or a sitemap)."""

    url: str
    body: str
    last_modified: str | None


class UrlRow(NamedTuple):
    """One ``<url>`` row from a sitemap: its location and optional ``<lastmod>``."""

    loc: str
    lastmod: str | None


class _Response(Protocol):
    """The httpx-shaped response contract the fetcher relies on (read-only)."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str]: ...


def is_listing_url(url: str) -> bool:
    """True iff ``url`` names a listing (``robots.txt`` or a sitemap ``.xml``).

    This is the structural guarantee behind "no PDF is ever downloaded": the
    fetcher only ever requests URLs for which this returns ``True``. A query
    string is ignored so ``sitemap.xml?page=2`` still counts.
    """
    path = urlparse(url).path.lower()
    return path.endswith(".xml") or path.endswith("/robots.txt") or path == "/robots.txt"


def _last_modified(response: _Response) -> str | None:
    """Read the ``Last-Modified`` header case-insensitively, or ``None``."""
    for key, value in response.headers.items():
        if key.lower() == "last-modified":
            return value
    return None


@dataclass
class CourteousFetcher:
    """Sequential, rate-limited fetcher that aborts on non-2xx and refuses assets.

    ``get`` performs one HTTP GET and returns an httpx-shaped response;
    ``sleep`` spaces requests out. Both are injected so tests drive fixture
    bytes with no socket and no real waiting.
    """

    get: Callable[[str], _Response]
    sleep: Callable[[float], None] = time.sleep
    delay: float = DEFAULT_DELAY_SECONDS

    def fetch(self, url: str) -> FetchedListing:
        """Fetch a single listing, or raise :class:`SitemapFetchError`.

        Refuses non-listing URLs before any request (no PDF is fetched), waits
        the courtesy ``delay``, then aborts on any non-2xx rather than retrying.
        """
        if not is_listing_url(url):
            raise SitemapFetchError(
                f"refusing to fetch non-listing URL {url!r}: this stage indexes "
                "sitemaps only and never downloads a PDF or other asset"
            )
        if self.delay:
            self.sleep(self.delay)
        response = self.get(url)
        status = response.status_code
        if not 200 <= status < 300:
            raise SitemapFetchError(
                f"aborting: {url} returned HTTP {status} (likely rate-limited or "
                "blocked); not retrying in a loop — re-run later"
            )
        return FetchedListing(url=url, body=response.text, last_modified=_last_modified(response))


def parse_robots_sitemaps(text: str) -> list[str]:
    """Return the ``Sitemap:`` URLs declared in a ``robots.txt`` body, in order."""
    urls: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            candidate = stripped.split(":", 1)[1].strip()
            if candidate:
                urls.append(candidate)
    return urls


def _localname(tag: str) -> str:
    """Strip any ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def _parse_xml(text: str) -> ET.Element:
    """Parse sitemap XML with a DTD refused up front.

    A sitemap never carries a ``<!DOCTYPE>``; refusing one neutralises
    entity-expansion ("billion laughs") before the parser ever sees it.
    """
    head = text.lstrip()[:2048].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        raise SitemapFetchError("refusing sitemap XML with a DTD/entity declaration")
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:  # malformed listing — treat as a fetch failure
        raise SitemapFetchError(f"malformed sitemap XML: {exc}") from exc


def _child_text(element: ET.Element, name: str) -> str | None:
    """Return the text of the first child with local name ``name``, or ``None``."""
    for child in element:
        if _localname(child.tag) == name and child.text:
            return child.text.strip()
    return None


def parse_sitemap_index(text: str) -> list[str]:
    """Return the child sitemap URLs listed in a ``<sitemapindex>``."""
    root = _parse_xml(text)
    locs: list[str] = []
    for entry in root:
        if _localname(entry.tag) != "sitemap":
            continue
        loc = _child_text(entry, "loc")
        if loc:
            locs.append(loc)
    return locs


def parse_url_entries(text: str) -> list[UrlRow]:
    """Return the ``<url>`` rows (loc + optional lastmod) in a ``<urlset>``."""
    root = _parse_xml(text)
    rows: list[UrlRow] = []
    for entry in root:
        if _localname(entry.tag) != "url":
            continue
        loc = _child_text(entry, "loc")
        if loc:
            rows.append(UrlRow(loc=loc, lastmod=_child_text(entry, "lastmod")))
    return rows
