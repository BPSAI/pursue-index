#!/usr/bin/env python3
"""Build ``web/public/data/asr-diff-bundle.json`` from per-row
``asr_diff.jsonl`` sidecars (R7C.27).

``pursue_index.transcribe.asr_diff_runner.run_row`` writes one sidecar row
per ``(card_id, row_key)`` next to the transcript it diffs, on the NAS.
This script rolls those up to one entry per card -- the WORST status
across a card's rows, since one row flagged for review means the card
isn't clear even if its other rows agreed completely -- and writes the
committed bundle ``scripts/build_qc_coverage.py`` reads, the same publish
step ``clean-qc-bundle.json`` already uses.

Usage::

    python scripts/build_asr_diff_bundle.py --cards aud1,aud2,...
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json

from pursue_index.paths import repo_root
from pursue_index.transcribe import asr_diff_sidecar as sidecar

REPO_ROOT = repo_root()

DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "asr-diff-bundle.json"

# A row's status is "judged" or "review"; review wins any tie, since the
# whole point is to never hide a disagreement a human should see.
_STATUS_RANK = {"judged": 0, "review": 1}


def _card_status(rows: dict[str, dict]) -> str | None:
    statuses = [r.get("status") for r in rows.values() if r.get("status") in _STATUS_RANK]
    if not statuses:
        return None
    return max(statuses, key=lambda s: _STATUS_RANK[s])


def build(*, ocr_dir: Path, card_ids: list[str]) -> dict:
    """``{"cards": [{"card_id", "status"}, ...]}`` for every card with a
    completed comparison, sorted by card_id."""
    cards = []
    for card_id in card_ids:
        rows = sidecar.load_existing(ocr_dir / card_id / sidecar.SIDECAR_FILE)
        status = _card_status(rows)
        if status is not None:
            cards.append({"card_id": card_id, "status": status})
    cards.sort(key=lambda c: c["card_id"])
    return {"cards": cards}


def as_status_map(bundle: dict) -> dict[str, str]:
    """``{card_id: status}`` -- what ``build_qc_coverage.py`` passes to
    ``build_coverage``'s ``asr_diff_status`` parameter."""
    return {c["card_id"]: c["status"] for c in bundle["cards"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ocr-dir", type=Path, default=None,
        help="Transcript sidecar root (default: settings.ocr_dir).",
    )
    parser.add_argument(
        "--cards", required=True,
        help="Comma-separated AUD card_ids to roll up.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.ocr_dir is None:
        from pursue_index.config import settings
        ocr_dir = settings.ocr_dir
    else:
        ocr_dir = args.ocr_dir
    card_ids = [c.strip() for c in args.cards.split(",") if c.strip()]

    bundle = build(ocr_dir=ocr_dir, card_ids=card_ids)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"asr-diff-bundle: {len(bundle['cards'])} card(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
