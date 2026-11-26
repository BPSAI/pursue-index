"""NASA NTRS metadata-search fetcher (stub)."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pursue_index.sitemap_fetch import SitemapFetchError

NTRS_HOSTS_PATH = Path("data") / "provenance" / "ntrs-hosts.json"
SEARCH_PATH = "/api/citations/search"
PAGE_SIZE = 5
USER_AGENT = "pursue-index-provenance/1.0 (metadata search only)"
DELAY_SECONDS = 1.0


class NtrsFetchError(SitemapFetchError):
    """A request was refused or aborted."""


def search_url(query: str) -> str:
    return ""


@dataclass
class NtrsFetcher:
    get: Callable[[str, Mapping[str, str]], Any]
    hosts: Collection[str] = ()
    sleep: Callable[[float], None] = lambda _s: None
    delay: float = DELAY_SECONDS
    requests: int = 0
    status_counts: dict[int, int] = field(default_factory=dict)

    def fetch(self, url: str) -> dict[str, Any]:
        return {}

    def search(self, query: str) -> dict[str, Any]:
        return {}

    def fetch_counts(self) -> dict[str, Any]:
        return {}
