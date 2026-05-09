#!/usr/bin/env python3
"""Build the static novelty payload for the in-browser filter + provenance UI.

Reads ``data/novelty/latest.json`` (the sidecar ``pursue novelty compute``
writes) and emits a compact map at ``web/public/data/novelty.json``:

```
{
  "archive_id": "synthetic-placeholder",
  "computed_at": "...",
  "thresholds": {"high": 0.85, "partial": 0.70},
  "cards": {
    "<card_id>": {
      "disclosure_status": "novel" | "partial" | "previously-disclosed",
      "novelty_score": 0.0-1.0,
      "matches": [
        {"page": 1, "ref_archive": "...", "ref_card_id": "...", "ref_page": 1, "similarity": 0.91},
        ...top 3...
      ]
    }
  }
}
```

The UI fetches this once on /index and on /card/[id]. Card-keyed map
keeps lookup O(1). If the file is absent, the filter dropdown disables
and the provenance panel degrades to "novelty comparison pending."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO_ROOT / "data" / "novelty" / "latest.json"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "novelty.json"


def _compact_card(card: dict) -> dict:
    return {
        "disclosure_status": card["disclosure_status"],
        "novelty_score": card["novelty_score"],
        "matches": card.get("matches", []),
    }


def build(source: Path, out: Path) -> int:
    if not source.exists():
        print(f"source {source} not found; skipping", file=sys.stderr)
        return 1
    payload = json.loads(source.read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "archive_id": payload.get("archive_id", "unknown"),
        "computed_at": payload.get("computed_at", ""),
        "thresholds": payload.get("thresholds", {"high": 0.85, "partial": 0.70}),
        "cards": {c["card_id"]: _compact_card(c) for c in payload.get("cards", [])},
    }
    out.write_text(json.dumps(compact))
    n = len(compact["cards"])
    size_kb = out.stat().st_size / 1024.0
    print(f"wrote {n} cards to {out} ({size_kb:.1f} KB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    return build(args.source, args.out)


if __name__ == "__main__":
    sys.exit(main())
