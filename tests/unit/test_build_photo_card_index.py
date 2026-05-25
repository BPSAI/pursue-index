"""Tests for `scripts/build_photo_card_index.py`.

The build step walks the manifest + NAS OCR sidecars and emits an
allow-list of `card_id`s that are image-content-as-PDF: single-page
PDFs whose OCR text is too sparse to be a real text document. These
cards (B001-B024, the FBI Composite Sketch, the CENTCOM DOW-UAP-PR
declass-headers, etc.) should surface under the gallery's PHOTOGRAPHS
filter despite being `asset_type=PDF`, because content-wise they're
photographs that war.gov happened to wrap in a PDF container.

`asset_type=IMG` cards are NOT in this list — the gallery filter
already covers them via the existing `c.asset_type === "IMG"` predicate.
This file only catches the PDF-wrapped photographs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_photo_card_index  # type: ignore[import-not-found] # noqa: E402


def _meta(page_count: int) -> dict:
    return {"status": "ok", "page_count": page_count}


def _pages_jsonl(*pages_text: str) -> str:
    return "\n".join(
        json.dumps({"page": i + 1, "text": t})
        for i, t in enumerate(pages_text)
    ) + "\n"


def test_predicate_includes_single_page_pdf_with_sparse_ocr() -> None:
    # FBI Photo B007 fixture: scale marks + timestamp only
    card = {"card_id": "b007", "asset_type": "PDF"}
    assert build_photo_card_index.is_photo_pdf(
        card, page_count=1, page_text="15 10 5 5 10 15 12/31/99 18:10:02"
    )


def test_predicate_includes_zero_text_pdf() -> None:
    # FBI Composite Sketch: 0 chars OCR
    card = {"card_id": "sketch", "asset_type": "PDF"}
    assert build_photo_card_index.is_photo_pdf(card, page_count=1, page_text="")


def test_predicate_excludes_text_heavy_pdf() -> None:
    # Pajarito Astronomers Invitation: 843 chars of real text content
    card = {"card_id": "pajarito", "asset_type": "PDF"}
    long_text = "A-86-014-91-3 Borgman H-183 5/20/86 Pajarito Astronomers " * 20
    assert not build_photo_card_index.is_photo_pdf(card, page_count=1, page_text=long_text)


def test_predicate_excludes_multipage_pdf() -> None:
    # DOE-UAP-D001 PANTEX: 2-page mixed document
    card = {"card_id": "pantex", "asset_type": "PDF"}
    assert not build_photo_card_index.is_photo_pdf(
        card, page_count=2, page_text="PANTEX header / 200 chars"
    )


def test_predicate_excludes_non_pdf() -> None:
    # FBI Photo A001 is asset_type=IMG, already covered by IMG filter
    card = {"card_id": "a001", "asset_type": "IMG"}
    assert not build_photo_card_index.is_photo_pdf(card, page_count=1, page_text="")


def test_predicate_excludes_videos_and_audio() -> None:
    for atype in ("VID", "AUD"):
        card = {"card_id": "v", "asset_type": atype}
        assert not build_photo_card_index.is_photo_pdf(card, page_count=1, page_text="")


def test_predicate_threshold_is_500_chars() -> None:
    # Boundary: exactly 499 chars passes, 500 chars fails
    card = {"card_id": "boundary", "asset_type": "PDF"}
    assert build_photo_card_index.is_photo_pdf(card, page_count=1, page_text="x" * 499)
    assert not build_photo_card_index.is_photo_pdf(card, page_count=1, page_text="x" * 500)


def test_predicate_strips_whitespace_before_threshold_check() -> None:
    # 600 chars of leading whitespace + "hello" should count as 5 chars
    card = {"card_id": "ws", "asset_type": "PDF"}
    assert build_photo_card_index.is_photo_pdf(
        card, page_count=1, page_text=" " * 600 + "hello"
    )


def test_build_writes_card_ids_and_count(tmp_path: Path) -> None:
    """End-to-end: real NAS-like layout in tmp dir produces the expected JSON."""
    ocr_root = tmp_path / "ocr"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "photo-card-ids.json"

    # Three cards: one photo-PDF, one text-PDF, one IMG (should not be included)
    cards = [
        {"card_id": "photo1", "asset_type": "PDF", "title": "Photo 1"},
        {"card_id": "text1", "asset_type": "PDF", "title": "Real Document"},
        {"card_id": "img1", "asset_type": "IMG", "title": "Photo file"},
    ]
    manifest_path.write_text(json.dumps({"cards": cards}))

    # OCR sidecars: photo1 has sparse text, text1 has heavy text
    (ocr_root / "photo1").mkdir(parents=True)
    (ocr_root / "photo1" / "meta.json").write_text(json.dumps(_meta(page_count=1)))
    (ocr_root / "photo1" / "pages.jsonl").write_text(_pages_jsonl("12/31/99 18:00"))

    (ocr_root / "text1").mkdir(parents=True)
    (ocr_root / "text1" / "meta.json").write_text(json.dumps(_meta(page_count=1)))
    (ocr_root / "text1" / "pages.jsonl").write_text(_pages_jsonl("real document " * 100))

    build_photo_card_index.build(
        manifest_path=manifest_path, ocr_root=ocr_root, out_path=out_path
    )

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == ["photo1"]
    assert out["count"] == 1
    assert "generated_at" in out


def test_build_skips_pdfs_without_meta(tmp_path: Path) -> None:
    """PDFs with no OCR sidecar yet are skipped (not a hard failure)."""
    ocr_root = tmp_path / "ocr"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "out.json"

    cards = [{"card_id": "missing", "asset_type": "PDF", "title": "Missing OCR"}]
    manifest_path.write_text(json.dumps({"cards": cards}))
    ocr_root.mkdir()

    build_photo_card_index.build(
        manifest_path=manifest_path, ocr_root=ocr_root, out_path=out_path
    )

    out = json.loads(out_path.read_text())
    assert out["card_ids"] == []
    assert out["count"] == 0


def test_build_emits_deterministic_sorted_order(tmp_path: Path) -> None:
    """card_ids in the output are sorted so the file is byte-stable across reruns."""
    ocr_root = tmp_path / "ocr"
    manifest_path = tmp_path / "manifest.json"
    out_path = tmp_path / "out.json"

    cards = [
        {"card_id": "zzz", "asset_type": "PDF"},
        {"card_id": "aaa", "asset_type": "PDF"},
        {"card_id": "mmm", "asset_type": "PDF"},
    ]
    manifest_path.write_text(json.dumps({"cards": cards}))
    for cid in ("zzz", "aaa", "mmm"):
        (ocr_root / cid).mkdir(parents=True)
        (ocr_root / cid / "meta.json").write_text(json.dumps(_meta(page_count=1)))
        (ocr_root / cid / "pages.jsonl").write_text(_pages_jsonl(""))

    build_photo_card_index.build(
        manifest_path=manifest_path, ocr_root=ocr_root, out_path=out_path
    )
    out = json.loads(out_path.read_text())
    assert out["card_ids"] == ["aaa", "mmm", "zzz"]
