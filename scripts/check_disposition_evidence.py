"""Check each byte-change disposition's ``evidence_ref`` against its evidence report.

The reports are private and never in this repository, so the public check
(``byte_dispositions``) enforces only the format: 64 lowercase hex characters.
This script is the operator-side half: given a directory of evidence report
files, it recomputes the sha256 over each file's bytes and confirms every row's
``evidence_ref`` matches one of them. Files in subdirectories count too.

Usage::

    python scripts/check_disposition_evidence.py --evidence-dir DIR [--dispositions FILE]

Exit 0 when every row matches a report; 1 otherwise, naming each card whose
ref matches none. A missing or empty directory also fails when rows exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import argparse
import hashlib

from pursue_index.byte_dispositions import ByteDispositionError, load_byte_change_dispositions
from pursue_index.paths import repo_root


def report_shas(evidence_dir: Path) -> set[str]:
    """sha256 (lowercase hex) of every regular file's bytes under ``evidence_dir``."""
    return {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(evidence_dir.rglob("*"))
        if path.is_file()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dispositions", type=Path,
        default=repo_root() / "data" / "byte-change-dispositions.jsonl",
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = load_byte_change_dispositions(args.dispositions)
        if rows and not args.evidence_dir.is_dir():
            raise ByteDispositionError(f"evidence directory {args.evidence_dir} does not exist")
        shas = report_shas(args.evidence_dir) if rows else set()
    except (ByteDispositionError, OSError) as exc:
        print(f"disposition evidence: ERROR: {exc}", file=sys.stderr)
        return 1
    unmatched = [d for d in rows.values() if d.evidence_ref not in shas]
    for d in unmatched:
        print(
            f"disposition evidence: {d.card_id} (new {d.new_sha256}) evidence_ref "
            f"{d.evidence_ref} matches no report in {args.evidence_dir}"
        )
    status = "FAILED" if unmatched else "OK"
    print(
        f"disposition evidence: {status} ({len(rows)} row(s), {len(rows) - len(unmatched)} "
        f"matched, {len(shas)} report file(s))"
    )
    return 1 if unmatched else 0


if __name__ == "__main__":
    sys.exit(main())
