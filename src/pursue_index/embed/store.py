"""On-disk format for the embedding stage.

Splits the I/O details out of ``pipeline.py``: the JSON index, the binary
vector file, and the OCR-output walker. The pipeline orchestrates; this
module owns the byte-level shape.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class PageRow:
    card_id: str
    page: int
    text: str
    text_sha: str


@dataclass
class IndexRow:
    card_id: str
    page: int
    text_sha: str
    offset: int
    # Vestigial on-disk format field. It once marked rows hashed against the
    # retired alex-zhang42 IMAGE-DESCRIPTIONS augment (retired 2026-07-11) so
    # the build/publish dedupe could keep the augmented sibling. No new row is
    # ever augmented now; the field and the dedupe it drives are retained only
    # to correctly READ any index still carrying augmented rows from before the
    # retirement, and default to False.
    augmented: bool = False


@dataclass
class EmbedSummary:
    """Counters returned to the CLI / caller after a run.

    Note: an earlier version of this dataclass carried a ``pages`` field that
    held the entire post-run index (prior + new). It was never read by any
    caller and grew linearly with the corpus, so it's been dropped. If a
    future caller wants the rows, ``store.load_prior_index_rows`` reads them
    from disk on demand.
    """

    embedded: int = 0
    skipped: int = 0
    total_tokens: int = 0
    cards_seen: int = 0


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_card_pages(
    ocr_dir: Path,
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> list[PageRow]:
    """Walk OCR output, yielding ok-status pages in deterministic order.

    ``obs_lookup`` (see ``image_observations.load_observation_text``) supplies
    our own vision-pass text for genuinely image-only pages: when a page's base
    OCR is empty AND its ``(card_id, page)`` is in the lookup, that text becomes
    the page's searchable content instead of the page being dropped.
    """
    rows: list[PageRow] = []
    if not ocr_dir.exists():
        return rows
    for card_dir in sorted(ocr_dir.iterdir()):
        if not card_dir.is_dir():
            continue
        meta_path = card_dir / "meta.json"
        pages_path = card_dir / "pages.jsonl"
        if not (meta_path.exists() and pages_path.exists()):
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        if meta.get("status") != "ok":
            continue
        rows.extend(
            _read_card_pages(
                card_dir.name, pages_path, obs_lookup=obs_lookup
            )
        )
    return rows


def _read_card_pages(
    card_id: str,
    pages_path: Path,
    *,
    obs_lookup: dict[tuple[str, int], str] | None = None,
) -> list[PageRow]:
    """Yield non-empty PageRows. Pages with empty/whitespace-only text are
    dropped — Voyage rejects empty input strings with HTTP 400, and pages
    with no readable OCR content (near-blank scans the LLM marked
    ``[ILLEGIBLE]`` only, or simply blank) wouldn't contribute useful
    retrieval signal anyway.

    Exception: when ``obs_lookup`` carries our own vision-pass text for an
    empty-OCR page (a genuinely image-only page — a photograph, illustration,
    or blank archival cover), that text becomes the page's content instead of
    the page being dropped. This is the only searchable text such pages have.
    """
    rows: list[PageRow] = []
    with pages_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            text = row.get("text", "") or ""
            page = int(row["page"])
            if not text.strip():
                obs = obs_lookup.get((card_id, page)) if obs_lookup else None
                if not obs:
                    continue
                text = obs
            rows.append(
                PageRow(
                    card_id=card_id,
                    page=page,
                    text=text,
                    text_sha=text_sha(text),
                )
            )
    return rows


def load_existing_index(
    index_path: Path,
) -> tuple[dict[tuple[str, int, str], int], int]:
    """Return ``(seen_keys -> offset, dim)`` from an existing index, or empty."""
    if not index_path.exists():
        return {}, 0
    try:
        idx = json.loads(index_path.read_text())
    except json.JSONDecodeError:
        return {}, 0
    seen: dict[tuple[str, int, str], int] = {}
    for r in idx.get("pages", []):
        seen[(r["card_id"], int(r["page"]), r["text_sha"])] = int(r["offset"])
    return seen, int(idx.get("dim", 0))


def load_prior_index_rows(index_path: Path) -> list[IndexRow]:
    if not index_path.exists():
        return []
    prior = json.loads(index_path.read_text())
    return [
        IndexRow(
            card_id=r["card_id"],
            page=int(r["page"]),
            text_sha=r["text_sha"],
            offset=int(r["offset"]),
            augmented=bool(r.get("augmented", False)),
        )
        for r in prior.get("pages", [])
    ]


def vectors_to_bytes(vectors: list[list[float]]) -> bytes:
    """Serialize [N, D] float32 little-endian, contiguous."""
    flat: list[float] = []
    for v in vectors:
        flat.extend(v)
    return struct.pack(f"<{len(flat)}f", *flat)


def write_index(
    index_path: Path,
    model_id: str,
    dim: int,
    rows: list[IndexRow],
    *,
    augmented_by: dict[str, str] | None = None,
) -> None:
    """Write the index.json sidecar. ``augmented_by`` is included only when a
    run explicitly passes it (external-context provenance). The alex-zhang42
    image-tag augmentation that once set it was retired 2026-07-12; runs no
    longer resurrect a prior index's block, so a plain run writes none.
    """
    payload: dict[str, object] = {
        "model_id": model_id,
        "dim": dim,
        "n": len(rows),
        "created_at": datetime.now(UTC).isoformat(),
        "pages": [_index_row_to_dict(r) for r in rows],
    }
    if augmented_by is not None:
        payload["augmented_by"] = augmented_by
    index_path.write_text(json.dumps(payload, indent=2))


def _index_row_to_dict(r: IndexRow) -> dict[str, object]:
    """Per-row JSON shape. ``augmented`` is omitted when False to keep the
    on-disk shape backward-compatible with un-augmented runs.
    """
    out: dict[str, object] = {
        "card_id": r.card_id,
        "page": r.page,
        "text_sha": r.text_sha,
        "offset": r.offset,
    }
    if r.augmented:
        out["augmented"] = True
    return out
