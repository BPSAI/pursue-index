"""The one-redirect-hop rule for the sitemap fetcher.

A listing request may be answered by a single redirect. The target is accepted
only when it is https on the default port, on a pinned source host, and
itself a listing; anything else is refused so the scope decision stays in this
repo rather than with the server. Kept apart from the fetcher so the policy is read and tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any
from urllib.parse import urljoin, urlparse

__all__ = ["REDIRECT_STATUSES", "RedirectRefusedError", "fetch_counts", "redirect_target"]

REDIRECT_STATUSES = frozenset({301, 302, 307, 308})


class RedirectRefusedError(ValueError):
    """The redirect response named a target the fetcher may not request."""


def redirect_target(
    url: str,
    headers: Mapping[str, str],
    allowed_hosts: Collection[str],
    listing_ok: Callable[[str], bool],
) -> str:
    """Resolve ``Location`` against ``url`` and return it, or raise.

    ``listing_ok`` says whether a URL is an admissible listing; ``allowed_hosts``
    holds lower-cased hostnames, matched exactly.
    """
    get_list = getattr(headers, "get_list", None)
    if get_list is not None and len(get_list("location")) > 1:
        raise RedirectRefusedError("more than one Location header")
    location = next((v for k, v in headers.items() if k.lower() == "location"), "")
    if not location.strip():
        raise RedirectRefusedError("missing Location")
    if "@" in location or "\\" in location or any(ord(c) <= 0x20 or ord(c) >= 0x7F for c in location):
        raise RedirectRefusedError(f"{location!r} could be read as a different host by different parsers")
    target = urljoin(url, location)
    parts = urlparse(target)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or host not in allowed_hosts:
        raise RedirectRefusedError(f"{target!r} is not an https URL on a pinned source host")
    try:
        port = parts.port
    except ValueError:
        port = -1
    if port not in (None, 443):
        raise RedirectRefusedError(f"{target!r} does not use the default https port")
    if not listing_ok(target):
        raise RedirectRefusedError(f"{target!r} is not a listing")
    return target


def fetch_counts(fetcher: Any) -> dict[str, int]:
    """Request and redirect counts of a fetcher, for the run summary and output."""
    return {
        "requests": fetcher.requests,
        "redirects_followed": fetcher.redirects_followed,
        "redirects_refused": fetcher.redirects_refused,
    }
