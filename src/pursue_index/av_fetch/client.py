"""DVIDS page + direct asset fetch — reuses the war.gov Chrome-impersonation seam.

DVIDS ``/video/<id>`` pages and the DOD asset bytes they embed are fetched
through ``csv_fetcher.http_get`` (curl_cffi, ``impersonate="chrome"``) — the
SAME client war.gov itself is fetched through. Probed 2026-08-09 for T48.5: a
plain client gets 403'd by TLS fingerprinting on gated hosts elsewhere in this
project, but Chrome-impersonated curl_cffi reached both the DVIDS page and its
CDN-hosted asset cleanly (200 / not blocked). Public reuse seam mirrors
``pdf_health.py``: tests monkeypatch ``csv_fetcher.http_get`` to inject fake
transports.

The asset GET is bounded on both ends. The URL taken off the page is
checked to be an absolute http(s) reference on a host the page is expected
to serve media from — the page's own domain, derived from the page being
scraped, or the delivery network it publishes media through — and the same
check is applied to the response's final URL, so the bytes are known to
have come from an expected host however many hops the response took. The
body is read in chunks against a byte ceiling, so an oversized response is
left unread past the limit rather than taken in whole and measured after.

DVIDS serves AUD assets from the same ``/video/<id>`` page as VID — the
``/audio/<id>`` forms 404 (verified 2026-08-08, see ``ingest_release_videos.
resolve_dod_filename``). ``asset_type`` gates the PLAYER, never the URL, so
this module never branches on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from pursue_index import get_logger
from pursue_index.scrape import csv_fetcher

log = get_logger(__name__)

# Re-use the CSV fetcher's Chrome impersonation profile so a TLS/header gating
# shift trips this stage in lockstep with the CSV and PDF health checks.
_IMPERSONATE = "chrome"

_DVIDS_PAGE_URL = "https://www.dvidshub.net/video/{dvids_video_id}"

# The mp4 <source> tag DVIDS embeds directly in the page markup — NOT the
# .m3u8 HLS source (also present) and NOT the thumbnail/og:image DOD_
# reference (also present, a differently-hosted .jpg, never inside a <source>
# tag). First (only) match wins.
_DOD_SOURCE_RE = re.compile(
    r"<source\s+src=\"([^\"]+DOD_\d{8,12}[^\"]*\.mp4)\"[^>]*type=['\"]video/mp4"
)

# The numeric DOD asset id as it appears in either the asset URL or a
# DOD_<id>.mp4-style filename.
_DOD_ID_RE = re.compile(r"DOD_(\d{8,12})")

# The stage retrieves over HTTP, so an asset reference it can act on is an
# absolute URL in one of these schemes.
_FETCHABLE_SCHEMES = ("http", "https")

# A page serves its media either from its own site or from a delivery host
# that site publishes through. The site is derived from the page being
# scraped (see ``check_asset_url``); a delivery host cannot be — it is a
# different domain from the page's — so each one is named here in full. A
# delivery network is shared infrastructure, so naming the whole host rather
# than its network's suffix keeps the check to the media this site publishes.
ASSET_DELIVERY_HOSTS = ("d34w7g4gy10iej.cloudfront.net",)

# Ceiling on the bytes read for a single asset. Release A/V assets measured
# on the 2026-08-09 probe were single- and double-digit megabytes, so this
# sits roughly two orders of magnitude above one and never stands in the
# way of a real asset; it bounds what one item can read into memory. It is
# applied as the body arrives, so a response larger than this is left
# unread past the limit rather than being taken in whole and measured after.
MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024

# How much of a streamed body is pulled per read.
_STREAM_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AssetResponse:
    """The outcome of one asset GET.

    ``error`` is ``None`` when the response arrived from an expected host
    and its body was read in full within the ceiling. When ``error`` is
    set, ``body`` is empty: the caller has a stated reason to report and
    nothing to stage.
    """

    status_code: int
    content_type: str | None
    body: bytes
    error: str | None = None


def dvids_page_url(dvids_video_id: str) -> str:
    """The public ``/video/<id>`` page URL for ``dvids_video_id``."""
    return _DVIDS_PAGE_URL.format(dvids_video_id=dvids_video_id)


def _host_matches(host: str, suffix: str) -> bool:
    """True iff ``host`` is ``suffix`` or a subdomain of it.

    Matching is on whole labels, so a longer name that merely ends with the
    same characters is a different host.
    """
    return host == suffix or host.endswith("." + suffix)


def _site_domain(host: str) -> str:
    """``host`` without a leading ``www`` label — the site it belongs to.

    Derived by dropping that one label rather than by keeping a fixed number
    of trailing labels, so the answer never widens to a domain the page's
    operator does not hold: a site under a multi-part public suffix
    (``example.co.uk``) yields itself, not the suffix.
    """
    return host[4:] if host.startswith("www.") else host


def check_asset_url(url: str, *, page_url: str) -> str | None:
    """Return why ``url`` is not a usable asset reference, else ``None``.

    An asset reference is usable when it is an absolute http(s) URL whose
    host is the site serving ``page_url`` — derived from the page being
    scraped, not assumed — or one of the delivery hosts that site publishes
    its media through, each named in full.
    """
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"asset url is not an absolute url: {url!r}"
    if parsed.scheme.lower() not in _FETCHABLE_SCHEMES:
        return f"asset url is not an http(s) url: {url!r}"
    if not parsed.netloc:
        return f"asset url is not an absolute url: {url!r}"
    host = (parsed.hostname or "").lower()
    site = _site_domain((urlparse(page_url).hostname or "").lower())
    if _host_matches(host, site) or host in ASSET_DELIVERY_HOSTS:
        return None
    return f"asset url host is not an expected asset host: {host!r}"


def fetch_dvids_page(
    dvids_video_id: str, *, timeout: float = 20.0
) -> tuple[int, str] | None:
    """GET the public ``/video/<id>`` page. ``None`` on transport error.

    Returns ``(status_code, body)`` on any HTTP response (including 4xx/5xx)
    so callers can report the exact failure — only a transport-level
    exception (DNS, timeout, connection reset) collapses to ``None``.
    """
    url = dvids_page_url(dvids_video_id)
    try:
        resp = csv_fetcher.http_get(url, impersonate=_IMPERSONATE, timeout=timeout)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # surface any transport failure
        log.warning(
            "av_fetch.page.transport_error",
            dvids_video_id=dvids_video_id,
            exc_type=type(exc).__name__,
        )
        return None
    return int(getattr(resp, "status_code", 0)), getattr(resp, "text", "") or ""


def extract_dod_asset_url(body: str) -> str | None:
    """Return the direct DOD asset mp4 URL embedded in a ``/video/<id>`` page."""
    m = _DOD_SOURCE_RE.search(body)
    return m.group(1) if m else None


def extract_dod_id(url_or_filename: str) -> str | None:
    """Return the numeric DOD asset id from a URL or ``DOD_<id>.mp4`` filename."""
    m = _DOD_ID_RE.search(url_or_filename)
    return m.group(1) if m else None


def _read_bounded(resp: object, max_bytes: int) -> tuple[bytes, str | None]:
    """Read the body up to ``max_bytes``; stop there if it goes past.

    Returns ``(body, error)``. Reading stops at the first chunk that carries
    the total past the ceiling, so the bytes held never exceed the ceiling
    plus one chunk and the rest of the response is left unread.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=_STREAM_CHUNK_BYTES):  # type: ignore[attr-defined]
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return b"", f"asset body is larger than the {max_bytes} byte ceiling"
        chunks.append(chunk)
    return b"".join(chunks), None


def fetch_dod_asset(
    url: str,
    *,
    page_url: str,
    timeout: float = 300.0,
    max_bytes: int = MAX_ASSET_BYTES,
) -> AssetResponse | None:
    """GET the DOD asset bytes. ``None`` on transport error.

    The URL is checked against ``page_url`` before the request goes out and
    the response's final URL is checked after it comes back, so the bytes
    are known to have come from an expected asset host however many hops
    the response took. The body is read in bounded chunks against
    ``max_bytes``.
    """
    reason = check_asset_url(url, page_url=page_url)
    if reason is not None:
        return AssetResponse(0, None, b"", error=reason)
    try:
        resp = csv_fetcher.http_get(
            url, impersonate=_IMPERSONATE, timeout=timeout, stream=True
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # surface any transport failure
        log.warning("av_fetch.asset.transport_error", url=url, exc_type=type(exc).__name__)
        return None
    try:
        status = int(getattr(resp, "status_code", 0))
        headers = getattr(resp, "headers", None) or {}
        content_type = headers.get("content-type")
        final_url = str(getattr(resp, "url", "") or url)
        final_reason = check_asset_url(final_url, page_url=page_url)
        if final_reason is not None:
            return AssetResponse(status, content_type, b"", error=final_reason)
        body, size_reason = _read_bounded(resp, max_bytes)
        return AssetResponse(status, content_type, body, error=size_reason)
    finally:
        closer = getattr(resp, "close", None)
        if callable(closer):
            closer()
