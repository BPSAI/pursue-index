#!/usr/bin/env python3
"""Append asset-bytes-registry rows for the 6 tranche-2 cards.

Phase 2 follow-up to scripts/ingest_tranche_2.py. The registry is the
append-only audit log of every byte-payload upload to R2; one row per
(card_id, byte_sha256) pair.

URL / card_id derivation
------------------------
This script imports ``CARD_SPECS`` from ``ingest_tranche_2`` so the
manifest entries and the registry rows share a single source of truth.
If the canonical bundle URL or any zip-member filename changes, edit
``ingest_tranche_2.py`` and both scripts re-derive correctly.

Schema observed in `data/asset-bytes-registry.jsonl` (release-1 rows):
    card_id, asset_url, asset_filename, byte_sha256, byte_size,
    upstream_etag (optional), archive_key, current_key, fetched_at

Tranche-2 rows have:
    - upstream_etag = None (the operator pulled the bundle out-of-band;
      we never observed the war.gov ETag)
    - source = "war.gov/release_02" (matches the corrected URL path
      segment; the earlier "war.gov/release_2" tag was based on the
      wrong path guess)

Idempotent: a (card_id, byte_sha256) pair already present in the file
is skipped. So a re-run is a no-op.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import the single source of truth for card_id + asset_url derivation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest_tranche_2 import CARD_SPECS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "data" / "asset-bytes-registry.jsonl"

# byte_sha256 + byte_size per filename (content-addressed; unchanged by
# the URL correction since these are properties of the PDF bytes).
_BYTES_BY_FILENAME: dict[str, tuple[str, int]] = {
    "ODNI-UAP-D001_USPER_Narrative_Senior_USIC.pdf": (
        "87297ea7ad56473613924b4a11c1c88b42d99515b814c4a4f95d84d60013787e",
        34195,
    ),
    "CIA-UAP-D001_Intelligence_Information_Report_USSR_1973.pdf": (
        "d3039ed486d8400be3263c0c438b199abfdb8ac030156baff1536f007349d315",
        154038,
    ),
    "DOE-UAP-D001_PANTEX_Image.pdf": (
        "4c007724fa7325d211123c153e1ed3eb989635302a6d2cd8757319d7f69358de",
        164108,
    ),
    "DOE-UAP-D002_JamesTuck_Correspondence.pdf": (
        "324a9795356cc793ede04a2494fa2eb18be10847baa490f605a22572c75f51ec",
        554461,
    ),
    "DOE-UAP-D003_Pajarito_Astronomers.pdf": (
        "89ecb1163e42d3e8a215033b88e87ae3befe82a8dad1db112fae7e760bb756f4",
        360462,
    ),
    "DOW-UAP-D017_General_Correspondence_Of_Sandia.pdf": (
        "ec72132902a2f50d2ab032031386710fef1d1ae1face0226a90243f61d9347b4",
        68764801,
    ),
}


def existing_pairs(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    pairs: set[tuple[str, str]] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pairs.add((row["card_id"], row["byte_sha256"]))
    return pairs


def main() -> int:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    seen = existing_pairs(REGISTRY)
    added = 0
    with REGISTRY.open("a") as f:
        for spec in CARD_SPECS:
            filename = spec["asset_filename"]
            if filename not in _BYTES_BY_FILENAME:
                print(f"ERROR: no byte_sha256 known for {filename}", file=sys.stderr)
                return 1
            sha, size = _BYTES_BY_FILENAME[filename]
            card_id = spec["card_id"]
            url = spec["asset_url"]
            if (card_id, sha) in seen:
                print(f"  skip (already present): {card_id} {sha[:16]}", file=sys.stderr)
                continue
            row = {
                "card_id": card_id,
                "asset_url": url,
                "asset_filename": filename,
                "byte_sha256": sha,
                "byte_size": size,
                "upstream_etag": None,
                "archive_key": f"archive/{sha}.pdf",
                "current_key": f"{card_id}.pdf",
                "fetched_at": now_iso,
                "source": "war.gov/release_02",
            }
            f.write(json.dumps(row) + "\n")
            added += 1
    print(f"Appended {added} registry rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
