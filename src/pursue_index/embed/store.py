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

# Bracketed header for the alex-zhang42/ufo-pursue-open-atlas image-
# description block. Bracketing keeps it human-readable in chat snippets
# and makes ``worker/retrieve.js::makeSnippet`` naturally center on it
# when the query matches inside an image tag.
AUGMENT_BLOCK_HEADER = (
    "[[IMAGE-DESCRIPTIONS via alex-zhang42/ufo-pursue-open-atlas, mimo-v2.5]]"
)


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
    # True iff this row was hashed against text that included the
    # alex-zhang42 IMAGE-DESCRIPTIONS block. Lets the build/publish step
    # dedupe by ``(card_id, page)`` keeping the augmented sibling when
    # both an un-augmented prior row and a new augmented row coexist
    # (vaivora cross-cutting blocker #3).
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
    augment_lookup: dict[tuple[str, int], list[str]] | None = None,
) -> list[PageRow]:
    """Walk OCR output, yielding ok-status pages in deterministic order.

    ``augment_lookup`` is the optional alex-zhang42 image-tag join (see
    ``pursue_index.embed.atlas_join.load_atlas_index``); when provided,
    pages whose ``(card_id, page)`` is in the lookup get the IMAGE-
    DESCRIPTIONS block appended before ``text_sha`` is computed.
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
                card_dir.name, pages_path, augment_lookup=augment_lookup
            )
        )
    return rows


def _augment_text(text: str, image_tags: list[str]) -> str:
    """Append the bracketed IMAGE-DESCRIPTIONS block. Pure helper.

    Format is one bullet per tag; the bracket label tells downstream
    consumers (chat prompt, snippet builder) which lines came from the
    VLM vs our OCR.
    """
    if not image_tags:
        return text
    bullets = "\n".join(f"- {tag}" for tag in image_tags)
    return f"{text}\n\n{AUGMENT_BLOCK_HEADER}\n{bullets}"


def _read_card_pages(
    card_id: str,
    pages_path: Path,
    *,
    augment_lookup: dict[tuple[str, int], list[str]] | None = None,
) -> list[PageRow]:
    """Yield non-empty PageRows. Pages with empty/whitespace-only text are
    dropped — Voyage rejects empty input strings with HTTP 400, and pages
    with no readable OCR content (near-blank scans the LLM marked
    ``[ILLEGIBLE]`` only, or simply blank) wouldn't contribute useful
    retrieval signal anyway. Their absence from the embed index is the
    correct behavior: the chat retrieval surface should never surface them.

    When ``augment_lookup`` is provided, each page's text gets the
    IMAGE-DESCRIPTIONS block appended *before* ``text_sha`` is computed,
    so the augmented row is content-addressed distinctly from the
    un-augmented baseline (the existing idempotency layer treats it as a
    new row).
    """
    rows: list[PageRow] = []
    with pages_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            text = row.get("text", "") or ""
            if not text.strip():
                continue
            page = int(row["page"])
            if augment_lookup is not None:
                tags = augment_lookup.get((card_id, page))
                if tags:
                    text = _augment_text(text, tags)
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
    """Write the index.json sidecar. ``augmented_by`` is included only
    when the run injected external context (alex-zhang42 image tags); its
    presence is the forensic signal that augmentation happened.
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
