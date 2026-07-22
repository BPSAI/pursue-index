"""Build the curated alt-titles index for duplicate-card-id cohorts.

Accepts the collapse of duplicate card-ids and surfaces alt-titles in
the UI:

Upstream's PURSUE CSV occasionally lists the same `asset_url` (one
PDF) under multiple "card" entries with different titles and
different `dvids_video_id`s. Our `stable_card_id(asset_url, title)`
collapses them to a single card_id (correct behaviour — same bytes,
one card), but the alternative titles disappear from the deployed
view.

This script recovers them. It reads the latest raw CSV in
``data/raw/csv/<sha>.csv`` (whichever sha is current per
``data/last-known-csv-sha.txt``), re-parses the rows the same way
the pipeline does, groups by computed card_id, and emits
``data/card_alt_titles.json`` mapping ``card_id`` → list of alt
entries. The card detail page reads this file at build time and
surfaces a "Also cataloged upstream as:" section per card.

Schema of the output file:

  {
    "generated_at": "2026-05-16T00:00:00Z",
    "source_csv_sha": "c9cc83fcaf43...",
    "alts": {
      "ea029a05470b8f4e": [
        {"title": "DOW-UAP-PR032, Unresolved UAP Report...", "dvids_video_id": "1006078", "asset_filename": "..."},
        {"title": "DOW-UAP-PR031, Unresolved UAP Report...", "dvids_video_id": "1006076", "asset_filename": "..."}
      ],
      ...
    }
  }

The CANONICAL title (the one that wins the collapse) is NOT in the
alts list — it's already the card's primary title. Only the
ALTERNATIVES are listed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_DIR = _REPO_ROOT / "data" / "raw" / "csv"
DEFAULT_SHA_FILE = _REPO_ROOT / "data" / "last-known-csv-sha.txt"
DEFAULT_OUTPUT = _REPO_ROOT / "data" / "card_alt_titles.json"

# Import the pipeline's stable_card_id so we collapse exactly like the
# main parser does. Local-only import keeps the script's dependency
# surface minimal.
sys.path.insert(0, str(_REPO_ROOT / "src"))
from pursue_index.scrape.normalize import (  # noqa: E402
    clean_str,
    clean_title,
    stable_card_id,
)


def _read_current_csv_sha(sha_file: Path) -> str | None:
    if not sha_file.exists():
        return None
    text = sha_file.read_text().strip().splitlines()[0]
    return text.split()[0] if text else None


def _csv_rows(path: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out


def _compute_card_id(row: dict[str, str]) -> str | None:
    title = clean_title(row.get("Title"))
    if not title:
        return None
    asset_url = clean_str(row.get("PDF | Image Link"))
    return stable_card_id(asset_url, title)


def build_alts(rows: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """Group rows by card_id; for card_ids with multiple rows, list
    the second-and-beyond entries (the canonical title is row[0])."""
    by_card: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        cid = _compute_card_id(row)
        if not cid:
            continue
        by_card[cid].append(row)

    out: dict[str, list[dict[str, Any]]] = {}
    for cid, rs in by_card.items():
        if len(rs) <= 1:
            continue  # no alts to surface
        alts: list[dict[str, Any]] = []
        for r in rs[1:]:
            alts.append({
                "title": clean_title(r.get("Title")) or r.get("Title", ""),
                "dvids_video_id": clean_str(r.get("DVIDS Video ID")),
                "asset_filename": clean_str(r.get("PDF | Image Link", "").rsplit("/", 1)[-1] if r.get("PDF | Image Link") else None),
            })
        out[cid] = alts
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=None, help="Override raw CSV path; defaults to the current sha file.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sha-file", type=Path, default=DEFAULT_SHA_FILE)
    parser.add_argument("--csv-dir", type=Path, default=DEFAULT_CSV_DIR)
    args = parser.parse_args(argv)

    if args.csv:
        csv_path = args.csv
        sha = csv_path.stem
    else:
        sha = _read_current_csv_sha(args.sha_file)
        if not sha:
            print(f"missing or empty sha file: {args.sha_file}", file=sys.stderr)
            return 2
        csv_path = args.csv_dir / f"{sha}.csv"
        if not csv_path.exists():
            print(f"missing csv: {csv_path}", file=sys.stderr)
            return 2

    rows = _csv_rows(csv_path)
    alts = build_alts(rows)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv_sha": sha,
        "alts": alts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"wrote {len(alts)} alt-title cohort(s) to {args.output}")
    for cid, entries in alts.items():
        print(f"  {cid}  ({len(entries)} alt(s))")
        for e in entries[:3]:
            print(f"    - {e['title'][:60]}  dvids={e.get('dvids_video_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
