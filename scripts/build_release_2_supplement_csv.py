#!/usr/bin/env python3
"""Generate the editorial CSV supplement for release_02.

Tranche 2 has NO upstream CSV — the war.gov uap-csv.csv only enumerates
release_1. This script writes a CSV in the same column shape as the
upstream so a human reader has a flat-file rendering of the tranche.

The file is editorial / documentation only. The Astro build does NOT
read it. Pipeline source-of-truth lives in:
    data/manifests/latest.json

Per-card `PDF | Image Link` is the canonical bundle URL + filename
fragment (mirrors what's stored as ``asset_url`` in the manifest). The
fragment is a faithful pointer to the zip member.

Imports CARD_SPECS from scripts/ingest_tranche_2.py so manifest, registry,
and CSV always agree.

Run
---
    python3 scripts/build_release_2_supplement_csv.py

Writes:
    data/manifests/release_02_supplement.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_tranche_2 import CARD_SPECS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "data" / "manifests" / "release_02_supplement.csv"

# Mirror the war.gov column order. The trailing empties match the
# observed CSV (11 unused columns past Image VIRIN).
HEADER = [
    "Redaction",
    "Release Date",
    "Title",
    "Type",
    "Video Pairing",
    "PDF Pairing",
    "Description Blurb",
    "DVIDS Video ID",
    "Video Title",
    "Agency",
    "Incident Date",
    "Incident Location",
    "PDF | Image Link",
    "Modal Image",
    "Image Alt Text",
    "Image VIRIN",
] + [""] * 11

RELEASE_DATE = "5/22/26"
DESCRIPTION = "Released in tranche 2 (2026-05-22). Operator editorial pending."


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for spec in CARD_SPECS:
            row = [
                "",  # Redaction
                RELEASE_DATE,
                spec["title"],
                "PDF",
                "",  # Video Pairing
                "",  # PDF Pairing
                DESCRIPTION,
                "",  # DVIDS Video ID
                "",  # Video Title
                spec["agency"],
                "",  # Incident Date
                "",  # Incident Location
                spec["asset_url"],
                "",  # Modal Image
                "",  # Image Alt Text
                "",  # Image VIRIN
            ] + [""] * 11
            w.writerow(row)
    print(f"Wrote {OUTPUT} ({len(CARD_SPECS)} data rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
