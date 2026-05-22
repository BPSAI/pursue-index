"""Tests for ``scripts/build_review_priority.py``.

Aggregates per-page priority scores across the corpus into
``web/public/data/review-priority.json`` sorted descending.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_review_priority as brp  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_score_card_combines_signals(tmp_path: Path) -> None:
    """For a card with one good page and one bad page, the bad page
    surfaces with a higher priority score."""
    card_dir = tmp_path / "abcd"
    _write_jsonl(card_dir / "pages.jsonl", [
        {"page": 1, "text": "Normal text on a real page. " * 10, "confidence": 0.98},
        {"page": 2, "text": "@#$%xy@#$%qw" * 30, "confidence": 0.50},
    ])
    _write_jsonl(card_dir / "pages_cleaned.jsonl", [
        {"page": 1, "text_cleaned": "Normal text on a real page. " * 10,
         "input_sha256": "raw_1", "output_sha256": "cleaned_1"},
        {"page": 2, "text_cleaned": "@#$%xy@#$%qw" * 30,
         "input_sha256": "raw_2", "output_sha256": "cleaned_2"},
    ])
    scores = brp.score_card("abcd", card_dir, qc_path=card_dir / "absent_qc.jsonl")
    assert len(scores) == 2
    by_page = {s["page"]: s["review_priority"] for s in scores}
    assert by_page[1] < by_page[2]
    assert by_page[2] > 0.3


def test_score_card_uses_qc_verdict_when_present(tmp_path: Path) -> None:
    card_dir = tmp_path / "abcd"
    _write_jsonl(card_dir / "pages.jsonl", [
        {"page": 1, "text": "normal text here", "confidence": 0.98},
    ])
    _write_jsonl(card_dir / "pages_cleaned.jsonl", [
        {"page": 1, "text_cleaned": "normal text here",
         "input_sha256": "raw_1", "output_sha256": "cleaned_1"},
    ])
    _write_jsonl(card_dir / "pages_cleaned_qc.jsonl", [
        {"page": 1, "raw_sha256": "raw_1", "cleaned_sha256": "cleaned_1",
         "aggregate": {"verdict": "hard_fail", "hard_fail_count": 1, "soft_fail_count": 0}},
    ])
    scores = brp.score_card("abcd", card_dir, qc_path=card_dir / "pages_cleaned_qc.jsonl")
    assert scores[0]["review_priority"] == 1.0


def test_build_aggregates_across_cards_sorted_descending(tmp_path: Path) -> None:
    """Two cards each yielding one page; the higher-priority page comes first."""
    for cid, conf in [("aaaa", 0.99), ("bbbb", 0.55)]:
        card_dir = tmp_path / cid
        _write_jsonl(card_dir / "pages.jsonl", [
            {"page": 1, "text": "page text", "confidence": conf},
        ])
        _write_jsonl(card_dir / "pages_cleaned.jsonl", [
            {"page": 1, "text_cleaned": "page text",
             "input_sha256": "raw_1", "output_sha256": "cleaned_1"},
        ])
    out_path = tmp_path / "review-priority.json"
    brp.build(ocr_dir=tmp_path, card_ids=["aaaa", "bbbb"], out_path=out_path)
    payload = json.loads(out_path.read_text())
    assert payload["total_pages"] == 2
    assert payload["pages"][0]["card_id"] == "bbbb"  # higher priority first
    assert payload["pages"][1]["card_id"] == "aaaa"


def test_build_skips_card_without_cleaned_jsonl(tmp_path: Path) -> None:
    """A card with no cleaned data should be skipped, not crash."""
    out_path = tmp_path / "review-priority.json"
    brp.build(ocr_dir=tmp_path, card_ids=["nonexistent"], out_path=out_path)
    payload = json.loads(out_path.read_text())
    assert payload["total_pages"] == 0
