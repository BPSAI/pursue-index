#!/usr/bin/env python3
"""Fail-closed deploy gate: no static asset over the Workers size budget.

Cloudflare Workers rejects the whole deploy when any single static asset
exceeds 25 MiB. This gate fails (exit 1) when any file under the given roots
is larger than the 24 MiB budget, or when a ``*.chunks.json`` manifest
disagrees with its parts (missing, resized, or shadowed by a stale whole
file). Oversize payloads are fixed by publishing them through
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
    find_budget_violations,
    find_manifest_errors,
)

DEFAULT_ROOTS = (REPO_ROOT / "web" / "public", REPO_ROOT / "web" / "dist")


def check(roots: list[Path], budget: int) -> list[str]:
    problems = [
        f"{path}: {size:,} bytes exceeds the {budget:,}-byte budget"
        for path, size in find_budget_violations(roots, budget=budget)
    ]
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
        print(
            "  fix: publish oversize payloads as chunks "
            "(scripts/chunk_public_assets.py) and rebuild",
            file=sys.stderr,
        )
        return 1
    print(f"asset budget: OK ({', '.join(str(r) for r in roots)}; <= {args.budget_bytes:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
