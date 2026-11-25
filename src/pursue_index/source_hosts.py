"""Pinned allowlist of hosts the source enumeration may request from."""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pursue_index.sitemap_fetch import (
    CourteousFetcher,
    SitemapFetchError,
    is_listing_url,
    is_text_sitemap_url,
    normalize_host,
    parse_robots_sitemaps,
    parse_sitemap_index,
    parse_text_sitemap,
    parse_url_entries,
)

__all__ = ["SOURCE_HOSTS_PATH", "host_allowed", "load_source_hosts", "note_skipped", "walk_sitemaps"]

#: Committed config: ``{"comment": ..., "hosts": [...]}``.
SOURCE_HOSTS_PATH = Path("data") / "provenance" / "source-hosts.json"


def load_source_hosts(path: Path) -> frozenset[str]:
    """Load the pinned source-host allowlist, or refuse to run.

    A missing, unreadable, malformed or empty file raises
    :class:`SitemapFetchError`; there is no fallback host.
    """
    try:
        data = json.loads(path.read_text())
        raw = data["hosts"]
        hosts = {normalize_host(h) for h in raw}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise SitemapFetchError(f"source-host allowlist {path} is missing or malformed: {exc}") from exc
    if not isinstance(raw, list) or not hosts or None in hosts:
        raise SitemapFetchError(f"source-host allowlist {path} is empty or invalid; refusing to run")
    return frozenset(h for h in hosts if h)


def host_allowed(url: str, hosts: Collection[str]) -> bool:
    """https only, and the exact (lower-cased, dot-stripped) hostname is listed."""
    parts = urlparse(url)
    return parts.scheme == "https" and normalize_host(parts.hostname) in hosts


def note_skipped(url: str, kind: str) -> None:
    """Print the note for a URL skipped before any request."""
    print(f"source-index: skipping {kind} {url!r}: not an https URL on a pinned source host")


def walk_sitemaps(
    fetcher: CourteousFetcher, robots_url: str, allowed_hosts: Collection[str]
) -> tuple[list[Any], list[str], int]:
    """Walk robots → indexes → sitemaps; return ``(rows, index_urls, dropped)``.

    Every request, robots.txt included, must be ``https`` on a pinned host;
    anything else is refused before a request. A ``.txt`` sitemap is fetched
    only when robots.txt lists that exact URL; children of an XML index are
    followed only when they are ``.xml`` listings. No asset is ever requested.
    ``dropped`` counts unusable lines in text sitemaps.
    """
    hosts = frozenset(h for h in (normalize_host(h) for h in allowed_hosts) if h)
    if not hosts:
        raise SitemapFetchError("no pinned source hosts; refusing to run")
    if not host_allowed(robots_url, hosts):
        raise SitemapFetchError(f"refusing robots URL {robots_url!r}: not an https URL on a pinned source host")
    index_urls = parse_robots_sitemaps(fetcher.fetch(robots_url).body)
    declared = frozenset(u for u in index_urls if is_text_sitemap_url(u))
    rows: list[Any] = []
    dropped = 0
    for index_url in index_urls:
        if not host_allowed(index_url, hosts):
            note_skipped(index_url, "sitemap")
            continue
        if index_url in declared:
            text_rows, bad = parse_text_sitemap(fetcher.fetch(index_url, declared).body)
            rows.extend(text_rows)
            dropped += bad
            continue
        if not is_listing_url(index_url):
            continue
        for child in parse_sitemap_index(fetcher.fetch(index_url).body):
            if not is_listing_url(child):
                continue
            if not host_allowed(child, hosts):
                note_skipped(child, "child sitemap")
                continue
            rows.extend(parse_url_entries(fetcher.fetch(child).body))
    return rows, index_urls, dropped
