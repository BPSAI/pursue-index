"""Upstream reads for ``r2_archive_assets.py``: HEAD, and a streamed GET into a hash.

Nothing here holds a response body in memory: ``fetch_asset`` feeds each chunk to
the sha256 and to a file, so a multi-hundred-megabyte video costs one chunk of RAM.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests as cffi_requests

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

_now = time.monotonic


class FetchTimeoutError(TimeoutError):
    """The stream went idle, or the overall per-asset ceiling was passed."""


def head_asset(url: Any) -> tuple[int | None, str | None, str | None]:
    """Return (content_length, etag, last_modified); all None on failure.

    Used as a cheap pre-flight check. ``url`` may be a pydantic ``HttpUrl`` or a
    plain string; we coerce to str so curl_cffi gets a regular string.
    """
    try:
        resp = cffi_requests.head(str(url), impersonate="chrome", timeout=30)
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


def fetch_asset(url: Any, dest: Path) -> tuple[str, int]:
    """Stream a GET (curl_cffi Chrome impersonation) into ``dest``; return ``(sha256, size)``.

    The body is hashed and written chunk by chunk, never read whole. curl enforces the
    idle limit (below ``LOW_SPEED_LIMIT`` bytes/s for ``IDLE_TIMEOUT_S``) and the
    overall ceiling; the loop checks both between chunks as well.
    """
    digest = hashlib.sha256()
    size = 0
    started = last = _now()
    # curl_cffi's streamed Response is not a context manager, so it is closed
    # explicitly; the close releases the connection even when the read fails.
    resp = cffi_requests.get(
        str(url),
        impersonate="chrome",
        timeout=TOTAL_CEILING_S,
        stream=True,
        curl_options={_CURLOPT_LOW_SPEED_LIMIT: 1, _CURLOPT_LOW_SPEED_TIME: IDLE_TIMEOUT_S},
    )
    try:
        resp.raise_for_status()
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
                digest.update(chunk)
                fh.write(chunk)
                size += len(chunk)
    finally:
        resp.close()
    return digest.hexdigest(), size


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
