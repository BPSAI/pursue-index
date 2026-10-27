"""Stage both sides of a candidate's bytes into the content-addressed dir.

``scripts/tranche_diff.py --bytes-dir DIR`` (``tranche_resave``) reads
``DIR/<byte_sha256>.pdf`` and re-hashes each file before trusting it. This
module fills such a dir for the poll job, inside the job's temp dir only --
nothing here is ever written under the repository:

* the NEW side is the page counter's already-fetched file
  (``pdf_pages.FetchedPdfs.paths``), copied in under its sha;
* the OLD side is fetched credential-free from the URL the site already
  serves for the old card (``pdf_pages.fetch_pdf``: allowlisted host, size
  cap, redirect re-validation) and staged only when it hashes to the old
  card's registry sha (``data/asset-bytes-registry.jsonl``, last row wins).

A failure is a value, not an exception: ``StagedBytes.failure`` carries the
schema's ``byte_verdict_reason`` vocabulary (``new_fetch_failed``,
``old_fetch_failed``, ``old_sha_mismatch``), and a failed side has no path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pursue_index import get_logger
from pursue_index.scrape import pdf_pages
from pursue_index.scrape.pdf_urls import is_allowed_pdf_url

__all__ = ["NEW_FETCH_FAILED", "OLD_FETCH_FAILED", "OLD_SHA_MISMATCH", "StagedBytes",
           "stage_new", "stage_old"]

log = get_logger(__name__)

NEW_FETCH_FAILED = "new_fetch_failed"
OLD_FETCH_FAILED = "old_fetch_failed"
OLD_SHA_MISMATCH = "old_sha_mismatch"


@dataclass(frozen=True)
class StagedBytes:
    """One side's bytes: where they were staged (if trusted) and what they were."""

    path: Path | None
    sha256: str | None = None
    size: int | None = None
    failure: str | None = None


def _place(data: bytes, bytes_dir: Path) -> StagedBytes:
    sha = hashlib.sha256(data).hexdigest()
    path = bytes_dir / f"{sha}.pdf"
    path.write_bytes(data)
    return StagedBytes(path=path, sha256=sha, size=len(data))


def stage_new(fetched_path: Path | None, bytes_dir: Path) -> StagedBytes:
    """Copy the page counter's file for the new card into ``bytes_dir``."""
    if fetched_path is None:
        return StagedBytes(path=None, failure=NEW_FETCH_FAILED)
    try:
        data = Path(fetched_path).read_bytes()
    except OSError:
        return StagedBytes(path=None, failure=NEW_FETCH_FAILED)
    return _place(data, bytes_dir)


def stage_old(
    url: str | None,
    registry_sha: str | None,
    bytes_dir: Path,
    *,
    fetch: Callable[[str], bytes] = pdf_pages.fetch_pdf,
) -> StagedBytes:
    """Fetch the old card's public PDF; stage it only if it is the registry's bytes."""
    if not isinstance(url, str) or not is_allowed_pdf_url(url):
        return StagedBytes(path=None, failure=OLD_FETCH_FAILED)
    try:
        data = fetch(url)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 -- any failure is "unreachable"
        log.warning("tranche_ready.old_fetch_failed", url=url[:200],
                    error=f"{type(exc).__name__}: {exc}"[:200])
        return StagedBytes(path=None, failure=OLD_FETCH_FAILED)
    sha = hashlib.sha256(data).hexdigest()
    if registry_sha is None or sha != registry_sha:
        log.warning("tranche_ready.old_sha_mismatch", url=url[:200], fetched=sha,
                    registry=registry_sha)
        return StagedBytes(path=None, sha256=sha, size=len(data), failure=OLD_SHA_MISMATCH)
    return _place(data, bytes_dir)
