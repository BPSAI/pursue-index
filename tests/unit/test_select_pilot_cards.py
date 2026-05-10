"""Smoke test for the pilot card selector."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import select_pilot_cards  # type: ignore[import-not-found] # noqa: E402


def _seed_card(ocr_dir: Path, card_id: str, *, pages: int, conf: float) -> None:
    cdir = ocr_dir / card_id
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "meta.json").write_text(json.dumps({"status": "ok"}))
    rows = "\n".join(
        json.dumps({"page": i + 1, "text": f"p{i+1}", "confidence": conf})
        for i in range(pages)
    )
    (cdir / "pages.jsonl").write_text(rows + "\n")


def test_picks_high_medium_low_confidence_buckets(tmp_path: Path) -> None:
    ocr_dir = tmp_path / "ocr"
    # 15 cards: 5 high-page-count, 5 medium, 5 low-confidence + 5 filler.
    for i in range(5):
        _seed_card(ocr_dir, f"hi{i}", pages=200 + i, conf=90)
    for i in range(5):
        _seed_card(ocr_dir, f"md{i}", pages=20, conf=85)
    for i in range(5):
        _seed_card(ocr_dir, f"lo{i}", pages=10, conf=30 + i)
    for i in range(5):
        _seed_card(ocr_dir, f"fl{i}", pages=15, conf=70)

    manifest = tmp_path / "manifest.json"
    card_ids = (
        [f"hi{i}" for i in range(5)]
        + [f"md{i}" for i in range(5)]
        + [f"lo{i}" for i in range(5)]
        + [f"fl{i}" for i in range(5)]
    )
    manifest.write_text(json.dumps({
        "cards": [
            {"card_id": cid, "asset_type": "PDF"} for cid in card_ids
        ],
    }))
    stats = select_pilot_cards._gather_stats(manifest, ocr_dir)
    picked = select_pilot_cards._pick_buckets(stats)
    # All five highest-page cards must be in the pick.
    assert all(f"hi{i}" in picked for i in range(5))
    # All five lowest-confidence cards must be in the pick.
    assert all(f"lo{i}" in picked for i in range(5))
    # Deterministic: same input → same order
    picked_again = select_pilot_cards._pick_buckets(stats)
    assert picked == picked_again
