"""Courteous fetcher for the NASA NTRS metadata search.

This is the only thing in the NTRS source that touches the network, and it is
deliberately narrow:

* **One endpoint.** Only ``GET https://ntrs.nasa.gov/api/citations/search`` is
  ever requested. :meth:`NtrsFetcher.fetch` refuses any other path — in
  particular ``/api/citations/<id>/downloads`` and anything ending in ``.pdf`` —
  *before* a request is made, so no document body can be downloaded through it.
* **Pinned host, https only.** The host must be listed exactly in
  ``data/provenance/ntrs-hosts.json``; there is no suffix match and no wildcard.
* **No redirects.** The injected ``get`` must not follow them; a 3xx is a
  non-2xx and aborts like any other.
* **Sequential and rate-limited.** A fixed sleep precedes every request, with a
  generic User-Agent naming the purpose.
* **Abort, don't retry.** Any non-2xx (403 and 429 included) raises
  :class:`NtrsFetchError`; the caller makes no further request.

``get`` and ``sleep`` are injected, so the module is exercised against fixture
bytes with no socket and no real waiting.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

import httpx

from pursue_index.sitemap_fetch import SitemapFetchError, normalize_host
from pursue_index.source_hosts import host_allowed

__all__ = [
    "DELAY_SECONDS",
    "NTRS_HOSTS_PATH",
    "PAGE_SIZE",
    "SEARCH_PATH",
    "USER_AGENT",
    "NtrsFetchError",
    "NtrsFetcher",
    "default_get",
    "search_url",
]

#: Committed config, same shape as ``source-hosts.json``.
NTRS_HOSTS_PATH = Path("data") / "provenance" / "ntrs-hosts.json"

#: The one path this module will request.
SEARCH_PATH = "/api/citations/search"

#: Results asked for per search.
PAGE_SIZE = 5

USER_AGENT = "pursue-index-provenance/1.0 (metadata search only)"

#: Courtesy sleep before every request, in seconds.
DELAY_SECONDS = 1.0

MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_BASE = "https://ntrs.nasa.gov"
_TIMEOUT_SECONDS = 30.0


class NtrsFetchError(SitemapFetchError):
    """A request was refused before being made, or aborted on a bad reply."""


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...


def search_url(query: str) -> str:
    """The search URL for ``query`` — the only URL shape this module requests."""
    return f"{_BASE}{SEARCH_PATH}?{urlencode({'q': query, 'page.size': PAGE_SIZE})}"


def default_get(url: str, headers: Mapping[str, str]) -> httpx.Response:
    """One GET, redirects not followed. Only the CLI uses this."""
    return httpx.get(url, headers=dict(headers), follow_redirects=False, timeout=_TIMEOUT_SECONDS)


def _refusal(url: str, hosts: Collection[str]) -> str | None:
    """Why ``url`` may not be requested, or ``None`` when it may."""
    parts = urlparse(url)
    if not host_allowed(url, hosts):
        return "not an https URL on a pinned NTRS host"
    if parts.port is not None or parts.username is not None or parts.password is not None:
        return "an explicit port or credentials are not allowed"
    if parts.path != SEARCH_PATH:
        return f"only {SEARCH_PATH} is requested; no download, PDF or record path"
    return None


@dataclass
class NtrsFetcher:
    """Sequential, rate-limited, search-only fetcher that aborts on non-2xx."""

    get: Callable[[str, Mapping[str, str]], _Response]
    hosts: Collection[str] = ()
    sleep: Callable[[float], None] = time.sleep
    delay: float = DELAY_SECONDS
    requests: int = 0
    status_counts: Counter[int] = field(default_factory=Counter)

    def fetch(self, url: str) -> dict[str, Any]:
        """GET one search URL and return its parsed JSON, or raise."""
        hosts = frozenset(h for h in (normalize_host(h) for h in self.hosts) if h)
        reason = _refusal(url, hosts)
        if reason is not None:
            raise NtrsFetchError(f"refusing {url!r}: {reason}; no request made")
        self.sleep(self.delay)
        self.requests += 1
        response = self.get(url, {"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.status_counts[response.status_code] += 1
        if not 200 <= response.status_code < 300:
            raise NtrsFetchError(
                f"aborting: {url} returned HTTP {response.status_code} (rate-limited, blocked or "
                "redirected); not retrying — re-run later"
            )
        try:
            data = response.json()  # type: ignore[attr-defined]
        except ValueError as exc:
            raise NtrsFetchError(f"aborting: {url} did not return JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise NtrsFetchError(f"aborting: {url} returned JSON that is not an object")
        return data

    def search(self, query: str) -> dict[str, Any]:
        """Run one metadata search for ``query``."""
        return self.fetch(search_url(query))

    def fetch_counts(self) -> dict[str, Any]:
        """Request and per-status counts, JSON-ready."""
        return {
            "requests": self.requests,
            "status_counts": {str(k): v for k, v in sorted(self.status_counts.items())},
        }
