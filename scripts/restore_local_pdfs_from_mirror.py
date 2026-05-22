"""Restore the NAS canonical PDF tree (`pdfs/<card_id>/<asset_filename>`)
from the R2 content-addressed mirror (`r2-mirror/archive/<sha>.pdf`).

Sprint 4q-prep, 2026-05-22. Diagnosed during Sprint 4q dispatch:
only 6 of 122 PDF cards had local NAS copies. The other 116 lived
only on R2 + R2-mirror (content-addressed). Three-tier archive
contract requires all three; this script remediates.

The script walks `data/asset-bytes-registry.jsonl`, finds every row
with `asset_type` resolving to PDF (any row whose `asset_filename`
ends in `.pdf`), and ensures the file exists at the canonical
`<ocr_root>/<card_id>/<asset_filename>` path. If missing, copies
from `r2-mirror/archive/<byte_sha256>.pdf`. Real file copies — NOT
symlinks — per operator framing (a symlink isn't a third tier).

Idempotent: skips files that already exist at the target with the
expected byte size.

Usage::

    python scripts/restore_local_pdfs_from_mirror.py
    python scripts/restore_local_pdfs_from_mirror.py --dry-run

Exits non-zero if any expected file can't be restored (e.g.,
mirror copy is also missing — a real archive gap that needs
operator attention).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

NAS_ROOT = Path("/mnt/nas/personal/pursue")
PDFS_DIR = NAS_ROOT / "pdfs"
MIRROR_DIR = NAS_ROOT / "r2-mirror" / "archive"
REGISTRY = Path(__file__).resolve().parent.parent / "data" / "asset-bytes-registry.jsonl"


def _load_registry_pdf_rows() -> list[dict]:
    """Latest row per (card_id, asset_filename) for PDF assets only.
    Registry is append-only; later rows supersede earlier ones (e.g.,
    when bytes rotate on upstream silent-overlay)."""
    rows = []
    with REGISTRY.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            filename = row.get("asset_filename", "")
            if not isinstance(filename, str) or not filename.lower().endswith(".pdf"):
                continue
            rows.append(row)
    # Keep latest per (card_id, asset_filename). Registry is in file
    # order ≈ chronological, so a simple dict-overwrite gets newest-wins.
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.get("card_id", ""), row.get("asset_filename", ""))
        latest[key] = row
    return list(latest.values())


def _restore_one(row: dict, dry_run: bool) -> str:
    """Return one of: 'ok-exists', 'restored', 'missing-mirror',
    'missing-fields'."""
    card_id = row.get("card_id")
    filename = row.get("asset_filename")
    sha = row.get("byte_sha256")
    expected_size = row.get("byte_size")
    if not (card_id and filename and sha):
        return "missing-fields"
    target = PDFS_DIR / card_id / filename
    if target.exists():
        if expected_size and target.stat().st_size == expected_size:
            return "ok-exists"
        # Wrong size — treat as needing restore. Existing file is stale.
    mirror = MIRROR_DIR / f"{sha}.pdf"
    if not mirror.exists():
        return "missing-mirror"
    if dry_run:
        return "would-restore"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mirror, target)
    return "restored"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be restored without copying.")
    args = p.parse_args(argv)

    rows = _load_registry_pdf_rows()
    print(f"registry: {len(rows)} unique (card_id, filename) PDF rows")
    counts: Counter[str] = Counter()
    missing_details: list[tuple[str, str]] = []
    for row in rows:
        outcome = _restore_one(row, args.dry_run)
        counts[outcome] += 1
        if outcome == "missing-mirror":
            missing_details.append((row["card_id"], row.get("byte_sha256", "")))
    for k, v in counts.most_common():
        print(f"  {k}: {v}")
    if missing_details:
        print()
        print("MISSING FROM MIRROR (archive integrity gap):")
        for cid, sha in missing_details[:20]:
            print(f"  {cid}  archive/{sha[:16]}...pdf")
        if len(missing_details) > 20:
            print(f"  ... +{len(missing_details) - 20} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
