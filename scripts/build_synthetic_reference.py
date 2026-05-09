#!/usr/bin/env python3
"""Build the placeholder reference embedding index from passages.json.

Reads ``data/reference/synthetic/passages.json`` and emits an embed
artifact compatible with the embed pipeline's on-disk layout
(``vectors.bin`` float32 + ``index.json``). This is the v1 reference
corpus the novelty pipeline diffs against.

If ``VOYAGE_API_KEY`` is set, real Voyage-3 embeddings are used (so the
similarity scores against the live PURSUE index are meaningful). If
not, a deterministic 1024-dim hash embedding is generated so the
machinery is fully exercisable in the absence of an API key — but the
similarity scores against the real PURSUE corpus will be noise. The
emitted ``index.json`` records which mode was used.

This is explicitly a placeholder. See ``data/reference/README.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_DIM = 1024  # voyage-3 dimensionality
DEFAULT_MODEL = "voyage-3"
SOURCE_JSON = REPO_ROOT / "data" / "reference" / "synthetic" / "passages.json"
DEFAULT_OUT = REPO_ROOT / "data" / "reference" / "synthetic" / "embeddings"


def _hash_embed(text: str, dim: int) -> list[float]:
    """Deterministic float32 vector from sha256 chunks. Used when no API key."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Repeat-and-trim into ``dim`` int32s, then normalize to unit-ish floats in [-1, 1].
    needed_bytes = dim * 4
    blob = (digest * ((needed_bytes // len(digest)) + 1))[:needed_bytes]
    ints = struct.unpack(f"<{dim}i", blob)
    vec = [(i % 20000 - 10000) / 10000.0 for i in ints]
    # L2-normalize so cosine has range [-1, 1].
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm > 0 else vec


def _voyage_embed(passages: list[dict], model: str) -> tuple[list[list[float]], str]:
    """Call Voyage; returns (vectors, mode_label). Raises on failure."""
    import voyageai

    api_key = os.environ.get("VOYAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY not set")
    client = voyageai.Client(api_key=api_key)
    texts = [p["text"] for p in passages]
    result = client.embed(texts, model=model, input_type="document")
    return [list(v) for v in result.embeddings], "voyage"


def _embed(passages: list[dict], model: str, dim: int) -> tuple[list[list[float]], str]:
    """Try Voyage; fall back to deterministic hash embedding."""
    if os.environ.get("VOYAGE_API_KEY"):
        try:
            return _voyage_embed(passages, model)
        except Exception as exc:  # noqa: BLE001 — fall through to placeholder
            print(f"warn: voyage embed failed ({exc}); using hash placeholder.", file=sys.stderr)
    return [_hash_embed(p["text"], dim) for p in passages], "hash-placeholder"


def _vectors_to_bytes(vectors: list[list[float]]) -> bytes:
    flat = [v for row in vectors for v in row]
    return struct.pack(f"<{len(flat)}f", *flat)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE_JSON)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    args = parser.parse_args()

    payload = json.loads(args.source.read_text())
    passages = payload["passages"]
    if not passages:
        print("no passages in source file", file=sys.stderr)
        return 1

    vectors, mode = _embed(passages, args.model, args.dim)
    dim = len(vectors[0])

    out_dir = args.out_root / args.model
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vectors.bin").write_bytes(_vectors_to_bytes(vectors))

    pages = []
    for i, p in enumerate(passages):
        text_hash = hashlib.sha256(p["text"].encode("utf-8")).hexdigest()
        pages.append(
            {
                "card_id": p["id"],
                "page": 1,
                "text_sha": text_hash,
                "offset": i * dim * 4,
            }
        )
    index = {
        "model_id": args.model,
        "dim": dim,
        "n": len(vectors),
        "mode": mode,
        "archive_id": payload.get("archive_id", "synthetic-placeholder"),
        "created_at": datetime.now(UTC).isoformat(),
        "pages": pages,
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    print(
        f"wrote {len(vectors)} reference embeddings ({dim}d, mode={mode}) to {out_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
