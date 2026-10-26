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
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from pursue_index import get_logger
from pursue_index.scrape import csv_fetcher

if TYPE_CHECKING:
    from pursue_index.scrape.poll_snapshot import SnapshotDiffResult

log = get_logger(__name__)

_IMPERSONATE = "chrome"  # same profile as csv_fetcher and pdf_health
_TIMEOUT_S = 120


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


def page_targets(diff: SnapshotDiffResult) -> list[PageTarget]:
    """New PDF cards plus cards whose PDF moved, one target per card_id.

    "Byte-changed" here is a field change touching ``asset_url``: this lane
    has no byte registry, so a new URL is the change it can see.
    """
    seen: dict[str, PageTarget] = {}
    for card in diff.added:
        if card.asset_type == "PDF" and card.asset_url and card.card_id not in seen:
            seen[card.card_id] = PageTarget(card.card_id, str(card.asset_url))
    for change in diff.field_changes:
        url = _moved_pdf_url(change)
        cid = change.get("card_id")
        if url and isinstance(cid, str) and cid not in seen:
            seen[cid] = PageTarget(cid, url)
    return list(seen.values())


def _fetch(url: str) -> bytes:
    resp = csv_fetcher.http_get(url, impersonate=_IMPERSONATE, timeout=_TIMEOUT_S)
    status = int(getattr(resp, "status_code", 0))
    if status != 200:
        raise OSError(f"HTTP {status}")
    return bytes(getattr(resp, "content", b"") or b"")


def _fetch_one(target: PageTarget, workdir: Path, out: FetchedPdfs) -> None:
    try:
        path = workdir / f"{target.card_id}.pdf"
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


@contextmanager
def fetch_and_count(targets: Iterable[PageTarget]) -> Iterator[FetchedPdfs]:
    """Fetch and count each target; bytes live in a temp dir for the block."""
    with tempfile.TemporaryDirectory(prefix="pursue-tranche-pdfs-") as tmp:
        out = FetchedPdfs(workdir=Path(tmp))
        for target in targets:
            _fetch_one(target, out.workdir, out)
        yield out
