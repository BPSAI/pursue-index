"""Cosine top-1 comparison between PURSUE page vectors and a reference index.

The reference index is the same shape the embed pipeline writes — float32
``vectors.bin`` plus ``index.json`` — produced by running
``pursue embed run`` over a separately-OCR'd reference corpus (Black
Vault, Project Blue Book archive, etc.). This module owns the loader
and the per-page top-1 primitive; ``aggregate.py`` rolls page scores
up to ``disclosure_status``.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceRow:
    card_id: str
    page: int
    text_sha: str


@dataclass(frozen=True)
class ReferenceIndex:
    """Loaded reference embedding set, keyed by an opaque ``archive_id``.

    ``vectors`` is a list-of-lists float32 view; for the placeholder
    corpus it's tiny so the pure-Python loop in ``cosine_top1`` is fine.
    A larger index would warrant a numpy dot-product, but this lives
    behind the same function signature so the swap is local.
    """

    archive_id: str
    model_id: str
    dim: int
    rows: list[ReferenceRow]
    vectors: list[list[float]]


@dataclass(frozen=True)
class PageMatch:
    """Best reference match for a single PURSUE page."""

    page: int
    ref_card_id: str
    ref_page: int
    similarity: float
    archive_id: str


def _read_vectors(vectors_path: Path, n: int, dim: int) -> list[list[float]]:
    """Parse the float32 [N, D] little-endian blob the embed pipeline writes."""
    raw = vectors_path.read_bytes()
    expected = n * dim * 4
    if len(raw) != expected:
        raise RuntimeError(
            f"reference vectors.bin size {len(raw)} != n*dim*4 ({expected})"
        )
    flat = struct.unpack(f"<{n * dim}f", raw)
    return [list(flat[i * dim : (i + 1) * dim]) for i in range(n)]


def load_reference_index(ref_dir: Path, archive_id: str) -> ReferenceIndex:
    """Load ``{ref_dir}/{vectors.bin, index.json}`` into a ReferenceIndex.

    ``ref_dir`` is the per-model subdirectory the embed pipeline writes —
    typically ``{data_root}/reference/{archive}/embeddings/voyage-3``.
    """
    index_path = ref_dir / "index.json"
    vectors_path = ref_dir / "vectors.bin"
    payload = json.loads(index_path.read_text())
    n = int(payload["n"])
    dim = int(payload["dim"])
    rows = [
        ReferenceRow(
            card_id=r["card_id"],
            page=int(r["page"]),
            text_sha=r["text_sha"],
        )
        for r in payload.get("pages", [])
    ]
    vectors = _read_vectors(vectors_path, n, dim) if n > 0 else []
    return ReferenceIndex(
        archive_id=archive_id,
        model_id=str(payload.get("model_id", "")),
        dim=dim,
        rows=rows,
        vectors=vectors,
    )


def cosine_top1(query: list[float], refs: list[list[float]]) -> tuple[int, float]:
    """Return ``(best_index, similarity)`` for the highest-cosine reference.

    Cosine = dot(q, r) / (||q|| * ||r||). A zero query vector or empty
    reference list returns ``(-1 or 0, 0.0)`` — the caller handles the
    "no match" case explicitly rather than getting NaN.
    """
    if not refs:
        return -1, 0.0
    q_norm = math.sqrt(sum(x * x for x in query))
    if q_norm == 0.0:
        return 0, 0.0
    best_idx = 0
    best_sim = -1.0
    for i, r in enumerate(refs):
        r_norm = math.sqrt(sum(x * x for x in r))
        if r_norm == 0.0:
            sim = 0.0
        else:
            dot = sum(qi * ri for qi, ri in zip(query, r, strict=False))
            sim = dot / (q_norm * r_norm)
        if sim > best_sim:
            best_sim = sim
            best_idx = i
    return best_idx, max(best_sim, 0.0)
