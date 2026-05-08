#!/usr/bin/env python3
"""Build the static embedding payload for the in-browser chat surface.

Reads ``{data_root}/embeddings/{model_id}/`` (the float32 vectors.bin
plus index.json the embed pipeline writes) and emits a compact pair the
chat island can mmap:

- ``web/public/data/embeddings.bin`` — packed **float16** [N, D]
  little-endian. Halves the payload for a <1% recall delta on cosine
  retrieval; if that delta ever bites in benchmarks we flip back to f32.
- ``web/public/data/embed_index.json`` — ``{model_id, dim, n, pages}``
  where ``pages`` is the compact list-of-lists ``[[card_id, page], ...]``
  (offsets dropped — array index is the row number).

Run after ``pursue embed run`` completes::

    python scripts/build_embed_data.py
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "data"
DEFAULT_WARN_BYTES = 10 * 1024 * 1024  # 10 MB — chat-interface plan threshold


def _read_vectors(in_dir: Path) -> tuple[np.ndarray, dict]:
    index = json.loads((in_dir / "index.json").read_text())
    dim = int(index["dim"])
    n = int(index["n"])
    raw = (in_dir / "vectors.bin").read_bytes()
    if len(raw) != n * dim * 4:
        raise RuntimeError(
            f"vectors.bin size {len(raw)} != n*dim*4 ({n * dim * 4})"
        )
    floats = struct.unpack(f"<{n * dim}f", raw)
    arr = np.array(floats, dtype=np.float32).reshape(n, dim)
    return arr, index


def _compact_pages(index: dict) -> list[list]:
    rows = sorted(index["pages"], key=lambda r: r["offset"])
    return [[r["card_id"], int(r["page"])] for r in rows]


def _write_index(idx_path: Path, index: dict) -> None:
    idx_path.write_text(
        json.dumps(
            {
                "model_id": index["model_id"],
                "dim": int(index["dim"]),
                "n": int(index["n"]),
                "pages": _compact_pages(index),
            }
        )
    )


def _maybe_warn(size: int, threshold: int) -> None:
    if size <= threshold:
        return
    size_mb = size / (1024 * 1024)
    print(
        f"WARNING: embeddings.bin is {size_mb:.1f} MB > "
        f"{threshold / (1024 * 1024):.0f} MB threshold; "
        "consider server-side retrieval (chat-interface plan).",
        file=sys.stderr,
    )
    # Mirror to stdout so test capture sees it regardless of stream sampled.
    print(f"warn: payload {size_mb:.1f} MB exceeds threshold; revisit retrieval")


def build(
    embeddings_root: Path,
    model_id: str,
    out_dir: Path,
    warn_threshold_bytes: int = DEFAULT_WARN_BYTES,
) -> int:
    in_dir = embeddings_root / model_id
    if not (in_dir / "index.json").exists():
        print(f"index.json missing in {in_dir}", file=sys.stderr)
        return 1

    arr, index = _read_vectors(in_dir)
    arr_f16 = arr.astype(np.float16)

    out_dir.mkdir(parents=True, exist_ok=True)
    bin_path = out_dir / "embeddings.bin"
    idx_path = out_dir / "embed_index.json"

    # Little-endian float16 — explicit dtype keeps platform endianness sane.
    bin_path.write_bytes(arr_f16.astype("<f2").tobytes(order="C"))
    _write_index(idx_path, index)

    size = bin_path.stat().st_size
    size_mb = size / (1024 * 1024)
    print(
        f"wrote {bin_path} ({size_mb:.2f} MB, {arr.shape[0]} vectors × "
        f"{arr.shape[1]} dims float16)"
    )
    print(f"wrote {idx_path}")
    _maybe_warn(size, warn_threshold_bytes)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--embeddings-root",
        type=Path,
        default=settings.embeddings_dir,
        help="Root containing per-model dirs (defaults to PURSUE data_root/embeddings).",
    )
    parser.add_argument(
        "--model", default=settings.embed_model, help="Model id to publish."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Where to write embeddings.bin + embed_index.json.",
    )
    args = parser.parse_args()
    return build(
        embeddings_root=args.embeddings_root,
        model_id=args.model,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
