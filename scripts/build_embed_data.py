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

The published index holds exactly one row per ``(card_id, page)``, and only
for pages ``pages.json`` carries non-empty text for: the store is append-only
(a re-OCR'd page adds a row rather than replacing one) and retrieval reads
titles and snippets out of ``pages.json``, so a row without text there could
only ever produce a blank citation.

Run after ``pursue embed run`` and ``scripts/build_search_data.py``::

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
from pursue_index.embed.publish import (  # noqa: E402
    load_embed_eligible_keys,
    select_publish_rows,
)

DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "data"
DEFAULT_WARN_BYTES = 10 * 1024 * 1024  # 10 MB — chat-interface plan threshold


def _read_vectors(in_dir: Path) -> tuple[np.ndarray, dict]:
    """Read vectors.bin into a contiguous float32 [total, dim] array.

    ``total`` is derived from the actual file size, not ``index["n"]``.
    The embed store is append-only, so a re-embedded page leaves its
    superseded vector bytes on disk even after ``pipeline._persist`` drops
    the index reference. The kept rows index into this larger array via
    their original ``offset``; ``_filter_vectors`` slices to only the kept
    rows downstream.
    """
    index = json.loads((in_dir / "index.json").read_text())
    dim = int(index["dim"])
    raw = (in_dir / "vectors.bin").read_bytes()
    if len(raw) % (dim * 4) != 0:
        raise RuntimeError(
            f"vectors.bin size {len(raw)} not a multiple of dim*4 ({dim * 4})"
        )
    total = len(raw) // (dim * 4)
    if total < int(index["n"]):
        raise RuntimeError(
            f"vectors.bin holds {total} vectors but index references {index['n']} rows"
        )
    floats = struct.unpack(f"<{total * dim}f", raw)
    arr = np.array(floats, dtype=np.float32).reshape(total, dim)
    return arr, index


def _select_rows(index: dict, eligible: set[tuple[str, int]]) -> list[dict]:
    """Offset-sorted, publish-eligible, one row per ``(card_id, page)``."""
    return select_publish_rows(index["pages"], eligible)


def _compact_pages(rows: list[dict]) -> list[list]:
    """Collapse to the wire shape ``[[card_id, page], ...]``."""
    return [[r["card_id"], int(r["page"])] for r in rows]


def _filter_vectors(arr: np.ndarray, kept_rows: list[dict], dim: int) -> np.ndarray:
    """Slice ``arr`` to the rows we kept, ordered by their original offset."""
    indices = [r["offset"] // (dim * 4) for r in kept_rows]
    return arr[indices]


def _write_index(idx_path: Path, index: dict, kept_rows: list[dict]) -> None:
    payload: dict[str, object] = {
        "model_id": index["model_id"],
        "dim": int(index["dim"]),
        "n": len(kept_rows),
        "pages": _compact_pages(kept_rows),
    }
    idx_path.write_text(json.dumps(payload))


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
    pages_json: Path | None = None,
) -> int:
    in_dir = embeddings_root / model_id
    if not (in_dir / "index.json").exists():
        print(f"index.json missing in {in_dir}", file=sys.stderr)
        return 1
    pages_path = pages_json or (out_dir / "pages.json")
    if not pages_path.exists():
        print(
            f"pages.json missing at {pages_path}; cannot check publish "
            "eligibility. Build it first (scripts/build_search_data.py).",
            file=sys.stderr,
        )
        return 1

    arr, index = _read_vectors(in_dir)
    dim = int(index["dim"])
    kept_rows = _select_rows(index, load_embed_eligible_keys(pages_path))
    arr = _filter_vectors(arr, kept_rows, dim)
    arr_f16 = arr.astype(np.float16)

    out_dir.mkdir(parents=True, exist_ok=True)
    bin_path = out_dir / "embeddings.bin"
    idx_path = out_dir / "embed_index.json"

    # Little-endian float16 — explicit dtype keeps platform endianness sane.
    bin_path.write_bytes(arr_f16.astype("<f2").tobytes(order="C"))
    _write_index(idx_path, index, kept_rows)

    size = bin_path.stat().st_size
    size_mb = size / (1024 * 1024)
    dropped = int(index["n"]) - len(kept_rows)
    print(
        f"wrote {bin_path} ({size_mb:.2f} MB, {arr.shape[0]} vectors × "
        f"{arr.shape[1]} dims float16; dropped {dropped} superseded or "
        "ineligible rows)"
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
    parser.add_argument(
        "--pages-json",
        type=Path,
        default=None,
        help="pages.json used for publish eligibility (default: out-dir).",
    )
    args = parser.parse_args()
    return build(
        embeddings_root=args.embeddings_root,
        model_id=args.model,
        out_dir=args.out_dir,
        pages_json=args.pages_json,
    )


if __name__ == "__main__":
    sys.exit(main())
