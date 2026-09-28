#!/usr/bin/env python3
"""Fail-closed deploy gate: no static asset over the Workers size budget.

Cloudflare Workers rejects the whole deploy when any single static asset
exceeds 25 MiB. This gate fails (exit 1) when any file under the given roots
is larger than the 24 MiB budget, or when a ``*.chunks.json`` manifest
disagrees with its parts (missing, resized, or shadowed by a stale whole
file). Chunking only applies to files directly under ``<root>/data/``,
because the Worker reassembles ``/data/<name>`` only. An oversize file
anywhere else, or a chunk manifest outside top-level ``data/``, fails with
no chunking remedy offered. Top-level oversize payloads are fixed by
publishing them through
``pursue_index.release.chunked_asset.write_asset`` (the derivative builders
do) or ``scripts/chunk_public_assets.py``.

Default roots: ``web/public`` and, when a build has run, ``web/dist``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.release.chunked_asset import (  # noqa: E402
    BUDGET_BYTES,
    MANIFEST_SUFFIX,
    find_budget_violations,
    find_manifest_errors,
)

DEFAULT_ROOTS = (REPO_ROOT / "web" / "public", REPO_ROOT / "web" / "dist")


# Chunking is only sound for files directly under `<root>/data/`: the Worker
# reassembles `/data/<name>` and nothing deeper. Anywhere else an oversize
# file has to shrink or move; the gate fails rather than pointing at the
# chunker.
CHUNKABLE_DIR = "data"
NOT_CHUNKABLE = (
    "cannot be chunked (only top-level data/* files are reassembled at "
    "/data/<name>); shrink it or move it to top-level data/"
)


def _chunkable(path: Path, root: Path) -> bool:
    return path.parent == root / CHUNKABLE_DIR


def _oversize_problem(path: Path, size: int, root: Path, budget: int) -> str:
    head = f"{path}: {size:,} bytes exceeds the {budget:,}-byte budget"
    if _chunkable(path, root):
        return f"{head}; publish it as chunks with scripts/chunk_public_assets.py"
    return f"{head} and {NOT_CHUNKABLE}"


def check(roots: list[Path], budget: int) -> list[str]:
    problems: list[str] = []
    for root in roots:
        problems.extend(
            _oversize_problem(path, size, root, budget)
            for path, size in find_budget_violations([root], budget=budget)
        )
        if root.is_dir():
            problems.extend(
                f"{m}: chunk manifest outside top-level data/ is never reassembled "
                "(the Worker only serves /data/<name>)"
                for m in sorted(root.rglob(f"*{MANIFEST_SUFFIX}"))
                if not _chunkable(m, root)
            )
    problems.extend(find_manifest_errors(roots))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("roots", nargs="*", type=Path, help="directories to check")
    parser.add_argument("--budget-bytes", type=int, default=BUDGET_BYTES)
    args = parser.parse_args(argv)
    roots = args.roots or [r for r in DEFAULT_ROOTS if r.exists()]
    problems = check(roots, args.budget_bytes)
    if problems:
        print("asset budget: FAIL", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"asset budget: OK ({', '.join(str(r) for r in roots)}; <= {args.budget_bytes:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
