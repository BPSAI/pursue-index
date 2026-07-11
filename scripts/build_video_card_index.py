#!/usr/bin/env python3
"""Build the allow-list of card_ids that have a playable R2 video/audio.

A/V cards (``asset_type`` VID or AUD) carry no ``asset_url`` — war.gov never
surfaces a direct media link, so historically the card-detail page embedded
the DVIDS public player (keyed by ``dvids_video_id``). DVIDS removed/404'd
the source assets in 2026-07, breaking playback fleet-wide.

The bytes themselves live in our own Cloudflare R2 bucket (``pursue-pdfs``):
``scripts/ingest_release_videos.py`` uploads each A/V card's file to the
content-addressed ``archive/<sha>.mp4`` key PLUS a ``<card_id>.mp4``
current-pointer key, and appends a row to
``data/asset-bytes-registry.jsonl``. The Worker serves the current pointer
same-origin at ``/video/<card_id>.mp4`` (Range-enabled — see
``worker/pdf.js::serveR2Video``).

Not every A/V card has been ingested yet (Release 1's videos, for one, were
never staged into R2). This script emits
``web/src/data/video-card-ids.json`` — the set of card_ids that DO have a
``<card_id>.mp4`` current pointer in R2 — so the card-detail page can pick
the R2 player when the bytes exist and fall back to the DVIDS embed when
they don't, rather than rendering a broken same-origin player.

Predicate — a registry row grants a card R2 playback iff:
  - it has a non-empty ``card_id`` AND
  - its ``current_key`` ends with ``.mp4`` (the current-pointer object the
    ``/video/`` route serves; archive-only ``.mp4`` rows don't count).

Usage::

    python scripts/build_video_card_index.py
    python scripts/build_video_card_index.py --registry path.jsonl --out path.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_OUT = REPO_ROOT / "web" / "src" / "data" / "video-card-ids.json"


def is_playable_video_row(row: dict) -> bool:
    """Return True iff this registry row is a ``<card_id>.mp4`` current pointer.

    Only current-pointer ``.mp4`` keys are servable at ``/video/<id>.mp4``;
    archive-only rows (``current_key`` empty, bytes only under
    ``archive/<sha>.mp4``) are not, so they don't grant playback.
    """
    if not row.get("card_id"):
        return False
    current_key = row.get("current_key") or ""
    return current_key.endswith(".mp4")


def build(*, registry_path: Path, out_path: Path) -> None:
    """Read the asset-bytes registry, write the video-card-ids JSON."""
    card_ids: set[str] = set()
    if registry_path.exists():
        with registry_path.open() as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if is_playable_video_row(row):
                    card_ids.add(row["card_id"])

    ordered = sorted(card_ids)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "card_ids": ordered,
        "count": len(ordered),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(registry_path=args.registry, out_path=args.out)
    out = json.loads(args.out.read_text())
    print(f"video-card-ids: {out['count']} cards → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
