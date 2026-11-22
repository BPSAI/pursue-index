"""Upstream reads for ``r2_archive_assets.py``: HEAD, and a streamed GET into a hash.

Nothing here holds a response body in memory: ``fetch_asset`` feeds each chunk to
the sha256 and to a file, so a multi-hundred-megabyte video costs one chunk of RAM.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from _r2_hosts import (  # noqa: F401  (re-exported: callers import these from here)
    ANY_HOST,
    AnyHost,
    FetchLimitError,
    allowed_hosts_from_urls,
    check_hop,
    check_host,
    for_card,
    log_hop,
)
from curl_cffi import requests as cffi_requests

from pursue_index.asset_rows import rows_of_asset

CHUNK_SIZE = 1 << 20

# Read-progress timeout, not a fixed total: a large video arriving steadily must not
# be cut off, while a stalled connection fails after IDLE_TIMEOUT_S without bytes.
IDLE_TIMEOUT_S = 60
# Overall bound so a server trickling bytes cannot hold the job: one asset may use at
# most a third of the weekly workflow's 180-minute ``timeout-minutes`` budget.
TOTAL_CEILING_S = 60 * 60

# libcurl option numbers (curl_cffi's CurlOpt enum values, inlined so importing this
# module does not need curl_cffi.const).
_CURLOPT_LOW_SPEED_LIMIT = 19
_CURLOPT_LOW_SPEED_TIME = 20

# Upstream-fetch bounds. An asset may grow to twice its last recorded size, but never past
# the absolute ceiling (growth past 2x is an alert, past the ceiling a failure); redirects are
# capped and must stay on the manifest's own hosts or the approved list.
MAX_ASSET_BYTES = 2 * 1024**3
SIZE_GROWTH_FACTOR = 2
# The hard ceiling for an asset of known size: growth past this many times its
# last recorded size fails the card. Growth past SIZE_GROWTH_FACTOR only alerts.
HARD_GROWTH_FACTOR = 10
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_now = time.monotonic


class FetchTimeoutError(TimeoutError):
    """The stream went idle, or the overall per-asset ceiling was passed."""


class FetchOverCapError(FetchLimitError):
    """The asset is bigger than its byte cap (declared up front, or observed mid-stream)."""

    def __init__(self, *, observed: int, cap: int, declared: bool) -> None:
        self.observed, self.cap, self.declared = observed, cap, declared
        kind = "declared" if declared else "observed"
        super().__init__(f"{kind} size {observed} bytes is over the {cap}-byte cap")


def byte_cap(rows: list[dict[str, Any]]) -> int:
    """The growth cap: twice the last recorded size, never above the ceiling. Past it is an alert."""
    known = last_known_size(rows)
    if isinstance(known, int) and known > 0:
        return min(known * SIZE_GROWTH_FACTOR, MAX_ASSET_BYTES)
    return MAX_ASSET_BYTES


def hard_ceiling(rows: list[dict[str, Any]]) -> int:
    """The most bytes a fetch may read before the card fails.

    ``MAX_ASSET_BYTES`` for an asset with no recorded size; otherwise the larger of
    that and ``HARD_GROWTH_FACTOR`` times the last recorded size, so an asset that is
    already bigger than the absolute ceiling is never refused for its own size.
    """
    known = last_known_size(rows)
    if isinstance(known, int) and known > 0:
        return max(MAX_ASSET_BYTES, known * HARD_GROWTH_FACTOR)
    return MAX_ASSET_BYTES


def _open(method: Callable[..., Any], url: str, allowed_hosts, **kw: Any) -> Any:
    """Issue a request, following at most ``MAX_REDIRECTS`` redirects by hand.

    The host allowlist is checked on the original URL and on every redirect target
    before anything is requested from it. Returns the final (non-redirect) response.
    """
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        check_host(current, allowed_hosts)
        resp = method(current, allow_redirects=False, **kw)
        location = (getattr(resp, "headers", None) or {}).get("location")
        if getattr(resp, "status_code", 200) not in _REDIRECT_STATUSES or not location:
            return resp
        _close(resp)
        if hop == MAX_REDIRECTS:
            raise FetchLimitError(f"more than {MAX_REDIRECTS} redirects")
        target = urljoin(current, location)
        check_hop(current, target)
        log_hop(current, target, resp.status_code)
        current = target
    raise AssertionError("unreachable")  # pragma: no cover


def _close(resp: Any) -> None:
    close = getattr(resp, "close", None)
    if callable(close):
        close()


def head_asset(
    url: Any, allowed_hosts: Collection[str] | AnyHost
) -> tuple[int | None, str | None, str | None]:
    """Return (content_length, etag, last_modified); all None on failure.

    Used as a cheap pre-flight check. ``url`` may be a pydantic ``HttpUrl`` or a
    plain string; we coerce to str so curl_cffi gets a regular string. A host or
    redirect violation is a failure like any other (all None).
    """
    try:
        resp = _open(
            cffi_requests.head, str(url), allowed_hosts, impersonate="chrome", timeout=30
        )
        if resp.status_code >= 400:
            return None, None, None
        cl = resp.headers.get("content-length")
        return (
            int(cl) if cl else None,
            resp.headers.get("etag"),
            resp.headers.get("last-modified"),
        )
    except Exception:
        return None, None, None


def fetch_asset(
    url: Any,
    dest: Path,
    *,
    allowed_hosts: Collection[str] | AnyHost,
    max_bytes: int | None = None,
) -> tuple[str, int]:
    """Stream a GET (curl_cffi Chrome impersonation) into ``dest``; return ``(sha256, size)``.

    The body is hashed and written chunk by chunk, never read whole. curl enforces the
    idle limit (below ``LOW_SPEED_LIMIT`` bytes/s for ``IDLE_TIMEOUT_S``) and the
    overall ceiling; the loop checks both between chunks as well.

    ``max_bytes`` aborts a body that grows past it (a declared Content-Length over it
    is refused before any byte is read); ``allowed_hosts`` (required; ``ANY_HOST`` to opt
    out) confines the URL and every redirect; more than ``MAX_REDIRECTS`` redirects is refused. Each violation raises
    ``FetchLimitError``.
    """
    digest = hashlib.sha256()
    size = 0
    started = last = _now()
    # curl_cffi's streamed Response is not a context manager, so it is closed
    # explicitly; the close releases the connection even when the read fails.
    resp = _open(
        cffi_requests.get,
        str(url),
        allowed_hosts,
        impersonate="chrome",
        timeout=TOTAL_CEILING_S,
        stream=True,
        curl_options={_CURLOPT_LOW_SPEED_LIMIT: 1, _CURLOPT_LOW_SPEED_TIME: IDLE_TIMEOUT_S},
    )
    try:
        resp.raise_for_status()
        declared = (getattr(resp, "headers", None) or {}).get("content-length")
        if max_bytes is not None and declared and declared.isdigit() and int(declared) > max_bytes:
            raise FetchOverCapError(observed=int(declared), cap=max_bytes, declared=True)
        with Path(dest).open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                now = _now()
                if now - last > IDLE_TIMEOUT_S:
                    raise FetchTimeoutError(
                        f"idle: no bytes for {now - last:.0f}s (limit {IDLE_TIMEOUT_S}s)"
                    )
                if now - started > TOTAL_CEILING_S:
                    raise FetchTimeoutError(
                        f"ceiling: fetch ran {now - started:.0f}s (limit {TOTAL_CEILING_S}s)"
                    )
                last = now
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise FetchOverCapError(observed=size, cap=max_bytes, declared=False)
                digest.update(chunk)
                fh.write(chunk)
    finally:
        resp.close()
    return digest.hexdigest(), size


def rows_for_asset(
    rows: list[dict[str, Any]] | None, asset_url: Any, asset_filename: Any = None
) -> list[dict[str, Any]]:
    """The earlier rows of one asset (oldest first): those at the fetched URL, else the
    card's rows of the same file type when the asset moved; empty means net-new."""
    return rows_of_asset(rows, asset_url, asset_filename)


def last_known_size(rows: list[dict[str, Any]]) -> int | None:
    return rows[-1].get("byte_size") if rows else None


def last_known_etag(rows: list[dict[str, Any]]) -> str | None:
    return rows[-1].get("upstream_etag") if rows else None


def head_identical(
    rows: list[dict[str, Any]],
    cl: int | None,
    etag: str | None,
    last_modified: str | None = None,
) -> bool:
    """True only when HEAD agrees with the last row's recorded validators.

    With an ETag on both sides, size and ETag must be equal. Without one, the
    fallback is Content-Length plus Last-Modified: both present and equal to the
    values recorded on the last row (a row without Last-Modified cannot use it).
    """
    if not rows or cl is None or cl != last_known_size(rows):
        return False
    recorded_etag = last_known_etag(rows)
    if etag is not None and recorded_etag is not None:
        return etag == recorded_etag
    if etag is not None or recorded_etag is not None:
        return False  # one side has an ETag and the other does not: not comparable
    recorded_lm = rows[-1].get("upstream_last_modified")
    return last_modified is not None and last_modified == recorded_lm
