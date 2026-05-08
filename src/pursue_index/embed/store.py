"""On-disk format for the embedding stage.

Splits the I/O details out of ``pipeline.py``: the JSON index, the binary
vector file, and the OCR-output walker. The pipeline orchestrates; this
module owns the byte-level shape.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
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


@dataclass
class EmbedSummary:
    embedded: int = 0
    skipped: int = 0
    total_tokens: int = 0
    cards_seen: int = 0
    pages: list[IndexRow] = field(default_factory=list)


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def iter_card_pages(ocr_dir: Path) -> list[PageRow]:
    """Walk OCR output, yielding ok-status pages in deterministic order."""
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
        rows.extend(_read_card_pages(card_dir.name, pages_path))
    return rows


def _read_card_pages(card_id: str, pages_path: Path) -> list[PageRow]:
    rows: list[PageRow] = []
    with pages_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            text = row.get("text", "") or ""
            rows.append(
                PageRow(
                    card_id=card_id,
                    page=int(row["page"]),
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
    index_path: Path, model_id: str, dim: int, rows: list[IndexRow]
) -> None:
    payload: dict[str, object] = {
        "model_id": model_id,
        "dim": dim,
        "n": len(rows),
        "created_at": datetime.now(UTC).isoformat(),
        "pages": [
            {
                "card_id": r.card_id,
                "page": r.page,
                "text_sha": r.text_sha,
                "offset": r.offset,
            }
            for r in rows
        ],
    }
    index_path.write_text(json.dumps(payload, indent=2))
