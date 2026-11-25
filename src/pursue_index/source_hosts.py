"""Pinned allowlist of hosts the source enumeration may request from."""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from urllib.parse import urlparse

from pursue_index.sitemap_fetch import SitemapFetchError, normalize_host

__all__ = ["SOURCE_HOSTS_PATH", "host_allowed", "load_source_hosts", "note_skipped"]

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
