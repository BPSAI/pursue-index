"""Verify the polled CSV bytes before the workflow commits them to main.

The poll workflow commits ``data/raw/csv/<sha>.csv`` straight to ``main``.
Upstream controls those bytes, so the commit steps call this first: the file
must exist, stay under ``MAX_CSV_BYTES`` and hash to the sha the poll
reported (the registry sha). Exit 0 to commit, 1 to skip and report.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

MAX_CSV_BYTES = 5 * 1024 * 1024  # real tranche CSVs are well under 1 MiB
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def verify(csv_dir: Path, sha: str) -> str | None:
    """``None`` when ``<csv_dir>/<sha>.csv`` is safe to commit, else why not."""
    if not _SHA256_HEX.fullmatch(sha):
        return "malformed sha"
    path = csv_dir / f"{sha}.csv"
    if not path.is_file():
        return "file missing"
    size = path.stat().st_size
    if size > MAX_CSV_BYTES:
        return f"size {size} exceeds cap {MAX_CSV_BYTES}"
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        return "bytes do not match the registry sha"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("--dir", type=Path, default=Path("data/raw/csv"))
    args = parser.parse_args(argv)
    reason = verify(args.dir, args.sha)
    if reason is None:
        print(f"ok: {args.sha[:12]}")
        return 0
    print(f"skip: {args.sha[:12]}: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
