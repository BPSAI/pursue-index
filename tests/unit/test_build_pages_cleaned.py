"""Tests for the per-card sidecar → web mirror build step.

Aggregates every ``pages_cleaned.jsonl`` under ``settings.ocr_dir`` into a
single ``web/public/data/pages-cleaned.json`` with metadata about the
pilot run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_pages_cleaned  # type: ignore[import-not-found] # noqa: E402


def _write_sidecar(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _write_manifest(path: Path, card_ids: list[str]) -> None:
    cards = [
        {
            "card_id": cid, "title": f"card {cid}", "agency": "FBI",
            "asset_type": "PDF",
            "asset_url": f"https://example.test/{cid}.pdf",
            "release_date": "2025-01-01", "redacted": False, "raw": {},
        }
        for cid in card_ids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_url": "https://example.test/x.csv",
        "fetched_at": "2026-05-09T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": cards,
    }))


def test_build_emits_pages_keyed_payload(tmp_path: Path) -> None:
    """Output is `{meta, pages}` with one row per sidecar entry."""
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [
            {"page": 1, "card_id": "c1", "text_cleaned": "p1",
             "model_id": "claude-haiku-4-5-20251001",
             "input_sha256": "a" * 64},
            {"page": 2, "card_id": "c1", "text_cleaned": "p2",
             "model_id": "claude-haiku-4-5-20251001",
             "input_sha256": "b" * 64},
        ],
    )
    _write_sidecar(
        ocr_dir / "c2" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c2", "text_cleaned": "p3",
          "model_id": "claude-haiku-4-5-20251001",
          "input_sha256": "c" * 64}],
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "out" / "pages-cleaned.json"
    rc = build_pages_cleaned.build(
        ocr_dir=ocr_dir,
        manifest_path=manifest,
        out_path=out_path,
        source_tag="pilot-30-cards",
    )
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["meta"]["source"] == "pilot-30-cards"
    assert payload["meta"]["model_id"] == "claude-haiku-4-5-20251001"
    assert sorted(payload["meta"]["cards_covered"]) == ["c1", "c2"]
    pages = payload["pages"]
    assert len(pages) == 3
    page1 = next(p for p in pages if p["card_id"] == "c1" and p["page"] == 1)
    assert page1["text"] == "p1"
    assert page1["title"] == "card c1"  # joined from manifest


def test_build_handles_empty_ocr_dir(tmp_path: Path) -> None:
    """No sidecars yet → emits an empty pages array with metadata only."""
    ocr_dir = tmp_path / "ocr"
    ocr_dir.mkdir()
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    out_path = tmp_path / "out" / "pages-cleaned.json"
    rc = build_pages_cleaned.build(
        ocr_dir=ocr_dir,
        manifest_path=manifest,
        out_path=out_path,
        source_tag="empty",
    )
    assert rc == 0
    payload = json.loads(out_path.read_text())
    assert payload["pages"] == []
    assert payload["meta"]["cards_covered"] == []


def test_build_skips_cards_without_sidecars(tmp_path: Path) -> None:
    """A card_id present in the manifest but with no sidecar is not in cards_covered."""
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(
        ocr_dir / "c1" / "pages_cleaned.jsonl",
        [{"page": 1, "card_id": "c1", "text_cleaned": "x",
          "model_id": "m", "input_sha256": "0" * 64}],
    )
    # Empty stub for c2 (no JSONL) — must not crash, must not appear.
    (ocr_dir / "c2").mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, ["c1", "c2"])
    out_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest, out_path=out_path,
        source_tag="t",
    )
    payload = json.loads(out_path.read_text())
    assert payload["meta"]["cards_covered"] == ["c1"]
