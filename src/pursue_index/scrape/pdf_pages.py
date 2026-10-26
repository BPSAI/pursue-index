"""Fetch a tranche's new PDFs and count their pages, for the poll estimate.

The poll issue prices a tranche per page (``release/rates.py``), so the
credential-free snapshot job needs each new or byte-changed PDF's page count
before anyone downloads anything. This module fetches those PDFs through the
same Chrome-impersonation client the PDF health check uses
(``csv_fetcher.http_get``), so a TLS-gate shift shows up here too, and counts
pages with ``pypdf``.

The bytes are kept only in a temporary directory that lives for the ``with``
block of :func:`fetch_and_count`; nothing is written under the repository.
The result maps card_id to its local path so a later step in the same job
(R7C.31's classifier) can read the bytes without fetching them again.

A card whose fetch or parse fails is not an error: it is listed in
``fallback_card_ids`` and priced with the per-card guess, and the estimate is
marked partial.

Nothing the CSV says is trusted. A card id must be 16 lowercase hex characters
(it becomes a file name) and a URL must pass ``pdf_urls.is_allowed_pdf_url`` on
every hop; a target that fails either is skipped with a log line. A run is
bounded in bytes per PDF, in total time and in target count, and the targets a
bound cuts off fall back like any other unfetched card.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from pypdf import PdfReader

from pursue_index import get_logger
from pursue_index.card_id import InvalidCardIdError, require_card_id
from pursue_index.scrape import csv_fetcher
from pursue_index.scrape.pdf_urls import is_allowed_pdf_url

if TYPE_CHECKING:
    from pursue_index.scrape.poll_snapshot import SnapshotDiffResult

log = get_logger(__name__)

_IMPERSONATE = "chrome"  # same profile as csv_fetcher and pdf_health
_TIMEOUT_S = 120
# Bounds on untrusted input. The largest scanned release PDFs run to tens of
# MB; 100 MiB leaves ample headroom while keeping one hostile body from filling
# the runner's disk or memory.
_MAX_PDF_BYTES = 100 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
# A tranche is a few hundred cards at most; past this the run is not a poll.
_MAX_TARGETS = 500
# Wall-clock budget across every target (the per-request timeout is separate).
_TOTAL_BUDGET_S = 20 * 60
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_monotonic = time.monotonic


@dataclass(frozen=True)
class PageTarget:
    """One PDF card to fetch and count."""

    card_id: str
    url: str


@dataclass
class FetchedPdfs:
    """Page counts, local paths and fallbacks for one tranche's PDFs."""

    workdir: Path
    page_counts: dict[str, int] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)
    fallback_card_ids: list[str] = field(default_factory=list)


def _moved_pdf_url(change: dict[str, Any]) -> str | None:
    """The new URL when a field change moves the card's asset to a PDF."""
    for d in change.get("diffs") or []:
        new = d.get("new")
        if d.get("field") != "asset_url" or not isinstance(new, str):
            continue
        if new.lower().split("?", 1)[0].endswith(".pdf"):
            return str(new)
    return None


def _vet(card_id: object, url: object) -> bool:
    """True iff a target's id and URL are safe to build a path and a request from."""
    try:
        require_card_id(card_id)
    except InvalidCardIdError:
        log.warning("pdf_pages.skip.invalid_card_id", card_id=str(card_id)[:40])
        return False
    if not is_allowed_pdf_url(url):
        log.warning("pdf_pages.skip.disallowed_url", card_id=card_id, url=str(url)[:200])
        return False
    return True


def page_targets(diff: SnapshotDiffResult) -> list[PageTarget]:
    """New PDF cards plus cards whose PDF moved, one target per card_id.

    "Byte-changed" here is a field change touching ``asset_url``: this lane
    has no byte registry, so a new URL is the change it can see. A card whose
    id or URL fails validation is skipped and logged, never raised.
    """
    seen: dict[str, PageTarget] = {}
    for card in diff.added:
        url = str(card.asset_url) if card.asset_url else ""
        fresh = card.asset_type == "PDF" and url and card.card_id not in seen
        if fresh and _vet(card.card_id, url):
            seen[card.card_id] = PageTarget(card.card_id, url)
    for change in diff.field_changes:
        url = _moved_pdf_url(change)
        cid = change.get("card_id")
        if url and isinstance(cid, str) and cid not in seen and _vet(cid, url):
            seen[cid] = PageTarget(cid, url)
    return list(seen.values())


def _read_capped(resp: Any) -> bytes:
    """The body, abandoned (OSError) once it passes ``_MAX_PDF_BYTES``."""
    headers = getattr(resp, "headers", None) or {}
    declared = str(headers.get("Content-Length", "") or "")
    if declared.isdigit() and int(declared) > _MAX_PDF_BYTES:
        raise OSError(f"body over {_MAX_PDF_BYTES} bytes (declared {declared})")
    if not hasattr(resp, "iter_content"):
        body = bytes(getattr(resp, "content", b"") or b"")
        if len(body) > _MAX_PDF_BYTES:
            raise OSError(f"body over {_MAX_PDF_BYTES} bytes")
        return body
    buf = bytearray()
    for chunk in resp.iter_content(_CHUNK_BYTES):
        buf += chunk
        if len(buf) > _MAX_PDF_BYTES:
            raise OSError(f"body over {_MAX_PDF_BYTES} bytes")
    return bytes(buf)


def _fetch(url: str) -> bytes:
    """GET ``url``, following redirects by hand so each hop is re-validated."""
    for _ in range(_MAX_REDIRECTS + 1):
        if not is_allowed_pdf_url(url):
            raise OSError(f"URL not allowed: {url[:120]}")
        resp = csv_fetcher.http_get(
            url, impersonate=_IMPERSONATE, timeout=_TIMEOUT_S,
            allow_redirects=False, stream=True,
        )
        try:
            status = int(getattr(resp, "status_code", 0))
            if status in _REDIRECT_STATUSES:
                location = (getattr(resp, "headers", None) or {}).get("Location")
                if not location:
                    raise OSError(f"HTTP {status} without Location")
                url = urljoin(url, str(location))
                continue
            if status != 200:
                raise OSError(f"HTTP {status}")
            return _read_capped(resp)
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
    raise OSError("too many redirects")


def _fetch_one(target: PageTarget, workdir: Path, out: FetchedPdfs) -> None:
    try:
        path = workdir / f"{require_card_id(target.card_id)}.pdf"
        path.write_bytes(_fetch(target.url))
        pages = len(PdfReader(path).pages)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 -- any failure falls back per card
        log.warning("pdf_pages.fallback", card_id=target.card_id, url=target.url,
                    error=f"{type(exc).__name__}: {exc}"[:200])
        out.fallback_card_ids.append(target.card_id)
        return
    out.page_counts[target.card_id] = pages
    out.paths[target.card_id] = path


def _bounded(targets: Iterable[PageTarget]) -> tuple[list[PageTarget], list[PageTarget]]:
    """Split vetted targets into those within ``_MAX_TARGETS`` and the overflow."""
    vetted = [t for t in targets if _vet(t.card_id, t.url)]
    if len(vetted) > _MAX_TARGETS:
        log.warning("pdf_pages.limit.targets", limit=_MAX_TARGETS, total=len(vetted))
    return vetted[:_MAX_TARGETS], vetted[_MAX_TARGETS:]


@contextmanager
def fetch_and_count(targets: Iterable[PageTarget]) -> Iterator[FetchedPdfs]:
    """Fetch and count each target; bytes live in a temp dir for the block.

    Targets over the count limit, or left when the total time budget is spent,
    are not fetched and are listed in ``fallback_card_ids``.
    """
    with tempfile.TemporaryDirectory(prefix="pursue-tranche-pdfs-") as tmp:
        out = FetchedPdfs(workdir=Path(tmp))
        within, overflow = _bounded(targets)
        out.fallback_card_ids.extend(t.card_id for t in overflow)
        started = _monotonic()
        for i, target in enumerate(within):
            if _monotonic() - started > _TOTAL_BUDGET_S:
                log.warning("pdf_pages.limit.time", budget_s=_TOTAL_BUDGET_S,
                            unfetched=len(within) - i)
                out.fallback_card_ids.extend(t.card_id for t in within[i:])
                break
            _fetch_one(target, out.workdir, out)
        yield out
