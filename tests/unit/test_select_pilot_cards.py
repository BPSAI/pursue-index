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


def test_pick_buckets_backfills_when_buckets_overlap(tmp_path: Path) -> None:
    """Codex P2: bucket merge dedupes across high/medium/degraded but
    doesn't replenish, so an overlap (e.g. a high-page card that's also
    among the most degraded) yields fewer than 30 cards. The selector
    must backfill from unused candidates so the pilot always runs at
    full sample size when one is available.
    """
    # 35 candidates, but the top-degraded set fully overlaps the
    # high-page set — without backfill the result drops to 25.
    stats: list[select_pilot_cards._CardStat] = []
    for i in range(10):
        # high page count, also low confidence — overlaps both buckets.
        stats.append(select_pilot_cards._CardStat(
            card_id=f"hi{i:02d}", page_count=200 + i, mean_confidence=10 + i,
        ))
    for i in range(10):
        stats.append(select_pilot_cards._CardStat(
            card_id=f"md{i:02d}", page_count=20, mean_confidence=85,
        ))
    for i in range(15):
        stats.append(select_pilot_cards._CardStat(
            card_id=f"fl{i:02d}", page_count=15, mean_confidence=70,
        ))
    picked = select_pilot_cards._pick_buckets(stats)
    assert len(picked) == 30
    assert len(set(picked)) == 30  # all unique


def test_pick_buckets_does_not_invent_cards_when_pool_too_small(
    tmp_path: Path,
) -> None:
    """If fewer than 30 candidates exist total, return what's available
    rather than crashing or padding with empty strings.
    """
    stats = [
        select_pilot_cards._CardStat(
            card_id=f"c{i:02d}", page_count=20 + i, mean_confidence=80,
        )
        for i in range(12)
    ]
    picked = select_pilot_cards._pick_buckets(stats)
    assert len(picked) == 12
    assert len(set(picked)) == 12


def test_zero_confidence_card_lands_in_degraded_bucket(tmp_path: Path) -> None:
    """Codex P1: a card whose pages are ALL zero-confidence is the most
    degraded card possible — the OCR engine couldn't read anything. The
    selector must include it (mean_confidence == 0.0) rather than filter
    it out, so the pilot's degraded bucket can find genuinely-broken
    cards. Prior behaviour (``confidence > 0`` filter) silently dropped
    these cards from the candidate pool entirely.
    """
    ocr_dir = tmp_path / "ocr"
    # The "obviously broken" card — all pages zero-confidence.
    _seed_card(ocr_dir, "broken", pages=12, conf=0.0)
    # Filler at varying mid-range confidence so "broken" is clearly worst.
    for i in range(15):
        _seed_card(ocr_dir, f"fl{i:02d}", pages=20, conf=70 + i)

    manifest = tmp_path / "manifest.json"
    card_ids = ["broken"] + [f"fl{i:02d}" for i in range(15)]
    manifest.write_text(json.dumps({
        "cards": [
            {"card_id": cid, "asset_type": "PDF"} for cid in card_ids
        ],
    }))
    stats = select_pilot_cards._gather_stats(manifest, ocr_dir)
    # Broken card MUST be in the stats with mean_confidence == 0.0.
    by_id = {s.card_id: s for s in stats}
    assert "broken" in by_id, "zero-confidence card was filtered out"
    assert by_id["broken"].mean_confidence == 0.0
    assert by_id["broken"].page_count == 12

    picked = select_pilot_cards._pick_buckets(stats)
    # The all-zero card IS the most degraded — must land in the picks.
    assert "broken" in picked


def test_read_card_stats_skips_malformed_jsonl_lines(tmp_path: Path) -> None:
    """Codex P2: a single truncated/corrupt JSONL line must not crash the
    selector. ``_read_card_stats`` must skip the malformed line, log a
    structured warning, and process the remaining valid lines so the
    pilot can always be generated even with a slightly damaged sidecar.
    """
    ocr_dir = tmp_path / "ocr"
    cdir = ocr_dir / "c1"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "meta.json").write_text(json.dumps({"status": "ok"}))
    # Valid line, then truncated/malformed line, then another valid line.
    (cdir / "pages.jsonl").write_text(
        json.dumps({"page": 1, "text": "p1", "confidence": 80.0}) + "\n"
        + '{"page": 2, "text": "tru'  # truncated mid-string
        + "\n"
        + json.dumps({"page": 3, "text": "p3", "confidence": 90.0}) + "\n"
    )
    # Must not raise.
    stat = select_pilot_cards._read_card_stats(ocr_dir, "c1")
    assert stat is not None
    # Only the two valid lines contribute to the confidence aggregate.
    assert stat.page_count == 2
    assert stat.mean_confidence == 85.0


def test_read_card_stats_returns_none_when_all_lines_malformed(
    tmp_path: Path,
) -> None:
    """If every line is malformed, the function returns None rather than
    raising — consistent with the existing "no valid confidences" branch.
    """
    ocr_dir = tmp_path / "ocr"
    cdir = ocr_dir / "c1"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "meta.json").write_text(json.dumps({"status": "ok"}))
    (cdir / "pages.jsonl").write_text("{bad\n{also bad\n")
    stat = select_pilot_cards._read_card_stats(ocr_dir, "c1")
    assert stat is None


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
