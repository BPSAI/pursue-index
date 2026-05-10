#!/usr/bin/env python3
"""Pick the 30-card pilot sample for the LLM cleanup pass.

Selection contract (per `.paircoder/plans/llm-cleaned-reading-text.md`
and the implementation brief):

  - 10 cards with high page count (long FBI sections)
  - 10 cards with medium page count (DOW MISREPs)
  - 10 cards with degraded OCR (low mean per-page confidence)

Deterministic so the operator's live run picks the same sample the
spot-check guidance assumes. Inputs:

  - manifest (canonical scrape manifest)
  - OCR meta.json files under settings.ocr_dir/<card_id>/meta.json
  - per-card OCR pages.jsonl for confidence aggregation

Output: a comma-separated list on stdout, ready to feed
``pursue clean run --cards "$(./select_pilot_cards.py)"``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402


@dataclass
class _CardStat:
    card_id: str
    page_count: int
    mean_confidence: float


def _read_card_stats(ocr_dir: Path, card_id: str) -> _CardStat | None:
    """Return ``(card_id, page_count, mean_confidence)`` for one card."""
    meta_path = ocr_dir / card_id / "meta.json"
    pages_path = ocr_dir / card_id / "pages.jsonl"
    if not (meta_path.exists() and pages_path.exists()):
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get("status") != "ok":
        return None
    confidences: list[float] = []
    with pages_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            conf = row.get("confidence")
            # Codex P1: keep zero-confidence pages. They are not noise —
            # they're exactly the "OCR couldn't read this" signal the
            # degraded bucket needs to surface. Filter only entries
            # missing or non-numeric ``confidence`` values.
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))
    if not confidences:
        return None
    return _CardStat(
        card_id=card_id,
        page_count=len(confidences),
        mean_confidence=sum(confidences) / len(confidences),
    )


def _gather_stats(manifest_path: Path, ocr_dir: Path) -> list[_CardStat]:
    payload = json.loads(manifest_path.read_text())
    out: list[_CardStat] = []
    for card in payload["cards"]:
        if card.get("asset_type") != "PDF":
            continue
        stat = _read_card_stats(ocr_dir, card["card_id"])
        if stat is not None:
            out.append(stat)
    return out


_TARGET_PILOT_SIZE = 30


def _pick_buckets(stats: list[_CardStat]) -> list[str]:
    """Split into high/medium/low-confidence buckets and pick 10 each.

    Deterministic ordering: each bucket sorted by ``card_id`` after the
    primary criterion, so re-runs across machines pick the same sample.

    Codex P2 backfill: deduping across overlapping buckets can drop the
    result below the pilot target (e.g. a high-page card that's also
    among the most degraded gets counted once). After the bucket-merge
    pass, fill remaining slots from the broader pool — first by walking
    each bucket beyond the initial top-10 cut, then (last resort) any
    unused card sorted by ``card_id`` — to land on exactly
    ``_TARGET_PILOT_SIZE`` whenever the candidate pool is large enough.
    """
    high_pages = sorted(stats, key=lambda s: (-s.page_count, s.card_id))
    sorted_by_pages = sorted(stats, key=lambda s: s.page_count)
    n = len(sorted_by_pages)
    median_start = max(0, n // 2 - 5)
    medium_pages = sorted_by_pages[median_start:]
    degraded = sorted(stats, key=lambda s: (s.mean_confidence, s.card_id))
    fallback = sorted(stats, key=lambda s: s.card_id)
    seen: set[str] = set()
    picked: list[str] = []
    # First pass: top-10 from each bucket (the contractual sample shape).
    for bucket in (high_pages[:10], medium_pages[:10], degraded[:10]):
        for stat in bucket:
            if stat.card_id in seen:
                continue
            seen.add(stat.card_id)
            picked.append(stat.card_id)
    if len(picked) >= _TARGET_PILOT_SIZE:
        return picked[:_TARGET_PILOT_SIZE]
    # Backfill: walk each bucket past its initial slice, then the
    # global fallback list, until we hit the target or exhaust candidates.
    for bucket in (high_pages, medium_pages, degraded, fallback):
        for stat in bucket:
            if stat.card_id in seen:
                continue
            seen.add(stat.card_id)
            picked.append(stat.card_id)
            if len(picked) >= _TARGET_PILOT_SIZE:
                return picked
    return picked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path,
        default=REPO_ROOT / "data" / "manifests" / "latest.json",
    )
    parser.add_argument("--ocr-dir", type=Path, default=settings.ocr_dir)
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    args = parser.parse_args()
    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    stats = _gather_stats(args.manifest, args.ocr_dir)
    if not stats:
        print(
            "no OCR cards with status=ok found — run `pursue ocr run` first",
            file=sys.stderr,
        )
        return 1
    picked = _pick_buckets(stats)
    if args.format == "json":
        print(json.dumps(picked))
    else:
        print(",".join(picked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
