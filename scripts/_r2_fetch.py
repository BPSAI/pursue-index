"""Upstream reads for ``r2_archive_assets.py``: HEAD, and a streamed GET into a hash.

Nothing here holds a response body in memory: ``fetch_asset`` feeds each chunk to
the sha256 and to a file, so a multi-hundred-megabyte video costs one chunk of RAM.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from curl_cffi import requests as cffi_requests

CHUNK_SIZE = 1 << 20


def head_asset(url: Any) -> tuple[int | None, str | None]:
    """Return (content_length, etag) or (None, None) on failure.

    Used as a cheap pre-flight check. ``url`` may be a pydantic ``HttpUrl`` or a
    plain string; we coerce to str so curl_cffi gets a regular string.
    """
    try:
        resp = cffi_requests.head(str(url), impersonate="chrome", timeout=30)
        if resp.status_code >= 400:
            return None, None
        cl = resp.headers.get("content-length")
        etag = resp.headers.get("etag")
        return (int(cl) if cl else None, etag)
    except Exception:
        return None, None


def fetch_asset(url: Any, dest: Path) -> tuple[str, int]:
    """Stream a GET (curl_cffi Chrome impersonation) into ``dest``; return ``(sha256, size)``.

    The body is hashed and written chunk by chunk, never read whole.
    """
    digest = hashlib.sha256()
    size = 0
    with cffi_requests.get(
        str(url), impersonate="chrome", timeout=300, stream=True
    ) as resp:
        resp.raise_for_status()
        with Path(dest).open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                digest.update(chunk)
                fh.write(chunk)
                size += len(chunk)
    return digest.hexdigest(), size


def last_known_size(rows: list[dict[str, Any]]) -> int | None:
    return rows[-1].get("byte_size") if rows else None


def last_known_etag(rows: list[dict[str, Any]]) -> str | None:
    return rows[-1].get("upstream_etag") if rows else None


def head_identical(rows: list[dict[str, Any]], cl: int | None, etag: str | None) -> bool:
    """True only when HEAD reports a size and an ETag that both equal the last row's."""
    return (
        bool(rows)
        and cl is not None
        and etag is not None
        and cl == last_known_size(rows)
        and etag == last_known_etag(rows)
    )
