#!/usr/bin/env python3
"""Publish ``web/public/data`` payloads within the deploy size budget.

With no names, sweeps ``--root`` and splits every top-level file over the
budget into ordered parts plus a ``<name>.chunks.json`` manifest (lossless;
see ``pursue_index.release.chunked_asset``). Only top-level files are chunked,
because the Worker reassembles ``/data/<name>`` and nothing deeper. An
oversize nested file is left untouched and reported, and the sweep exits 1. Named assets are (re)published
through the same writer whatever their size, so each carries a manifest and
readers never probe for a missing one.

The derivative builders already write through ``write_asset``; this sweep is
the catch-all run last by ``make rebuild-derivatives``, and the way to chunk
committed payloads without the data root.
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
    read_asset_bytes,
    write_asset,
)

DEFAULT_ROOT = REPO_ROOT / "web" / "public" / "data"

# Payloads the site and Worker read through the chunk-aware loader. Each is
# always published with a manifest so the loader never has to probe.
MANAGED_ASSETS = ("embeddings.bin", "embed_index.json", "pages.json", "pages-cleaned.json")


def _is_chunk_artifact(path: Path) -> bool:
    return path.name.endswith(MANIFEST_SUFFIX) or ".part-" in path.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("names", nargs="*", help="asset names under --root to (re)publish")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--budget-bytes", type=int, default=BUDGET_BYTES)
    parser.add_argument(
        "--managed", action="store_true",
        help=f"also (re)publish {', '.join(MANAGED_ASSETS)} when present",
    )
    args = parser.parse_args(argv)

    nested_names = [n for n in args.names if Path(n).name != n]
    if nested_names:
        print(f"chunk: only top-level files can be chunked: {', '.join(nested_names)}",
              file=sys.stderr)
        return 1
    targets = [args.root / n for n in args.names]
    if args.managed:
        targets += [args.root / n for n in MANAGED_ASSETS if n not in args.names]
    refused: list[Path] = []
    for path, _size in find_budget_violations([args.root], budget=args.budget_bytes):
        if _is_chunk_artifact(path) or path in targets:
            continue
        # The Worker reassembles /data/<name> only; a nested file is left
        # alone and reported (the asset-budget gate fails on it too).
        (targets if path.parent == args.root else refused).append(path)

    for path in targets:
        try:
            data = read_asset_bytes(path)
        except FileNotFoundError:
            if path.name in args.names:
                print(f"chunk: {path} not found", file=sys.stderr)
                return 1
            continue
        written = write_asset(path, data, budget=args.budget_bytes)
        shape = "whole" if len(written) == 1 else f"{len(written)} parts"
        print(f"chunk: {path.name} ({len(data):,} bytes) -> {shape}")
    for path in refused:
        print(
            f"chunk: {path.relative_to(args.root)} is over budget but not a top-level "
            "file; only top-level data/* files can be chunked. Shrink or move it.",
            file=sys.stderr,
        )
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
