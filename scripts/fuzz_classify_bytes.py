#!/usr/bin/env python3
"""Differential fuzz run for the metadata-only re-save classifier.

Generates incremental-update PDF pairs, classifies each with
``tranche_bytes.classify_bytes`` and re-checks every ``metadata-only``
verdict against PDFium renders of both files (see
``pursue_index.classify_fuzz``). Exits 1 on any pair the classifier calls
``metadata-only`` that PDFium sees differ, 2 when the run produced no
``metadata-only`` verdict at all (a vacuous run proves nothing), else 0.

Bounded and offline: a fixed iteration count plus a wall-clock budget, no
credentials, no network. Deterministic for a given ``--seed``.

Usage::

    python scripts/fuzz_classify_bytes.py --iterations 2000 --seed 1234 \\
        --time-budget 900 --findings-dir fuzz-findings
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse

from pursue_index.classify_fuzz import run_fuzz


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--time-budget", type=float, default=600.0,
                        help="Stop generating new cases after this many seconds.")
    parser.add_argument("--isolated", action="store_true",
                        help="Classify in the resource-limited worker (slower; the production path).")
    parser.add_argument("--findings-dir", type=Path, default=None,
                        help="Write each finding's old/new PDFs and oracle note here.")
    args = parser.parse_args(argv)
    report = run_fuzz(args.iterations, args.seed, time_budget=args.time_budget,
                      isolated=args.isolated, findings_dir=args.findings_dir)
    print(report.summary())
    for case, difference in report.findings:
        print(f"finding: case {case.index} ops={','.join(case.ops)}: {difference}")
    if report.findings:
        return 1
    if report.verdicts["metadata-only"] == 0:
        print("no metadata-only verdict in the run: nothing was cross-checked")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
