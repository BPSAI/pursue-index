"""Tests for the OCR pipeline.

The actual Tesseract call is mocked at the ``ocr_image`` seam so these tests
run anywhere — no Tesseract binary needed. The integration smoke test in
``tests/integration/`` (TBD) is what proves the binary path.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.ocr.pipeline import ocr_card
from pursue_index.scrape.types import CardMetadata


def _pdf_card(card_id: str = "abc1234567890def") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="Test Card",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def _img_card() -> CardMetadata:
    return CardMetadata(
        card_id="img0000000000000",
        title="Image Card",
        asset_type="IMG",
        agency="NASA",
        asset_url="https://www.war.gov/img/x.jpg",
        asset_filename="x.jpg",
    )


def _patch_engine(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[tuple[str, float]],
) -> None:
    """Stub rasterize_pdf to yield N sentinel pages, ocr_image to return canned results."""

    def fake_rasterize(path: Path, dpi: int) -> Iterator[object]:
        for _ in pages:
            yield object()  # placeholder page image

    results = iter(pages)

    def fake_ocr_image(_: object) -> tuple[str, float]:
        return next(results)

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(ocr_pipeline, "ocr_image", fake_ocr_image)


def _write_fake_pdf(path: Path, content: bytes = b"%PDF-1.4 fake\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_ocr_card_writes_pages_jsonl_and_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_engine(monkeypatch, [("Page one text", 92.5), ("Page two text", 88.0)])

    card = _pdf_card()
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300)

    assert did_work is True
    pages_path = out_dir / "pages.jsonl"
    meta_path = out_dir / "meta.json"
    assert pages_path.exists()
    assert meta_path.exists()

    rows = [json.loads(line) for line in pages_path.read_text().splitlines()]
    assert [r["page"] for r in rows] == [1, 2]
    assert rows[0]["text"] == "Page one text"
    assert rows[0]["confidence"] == pytest.approx(92.5)
    assert rows[0]["engine"] == "tesseract"

    meta: dict[str, Any] = json.loads(meta_path.read_text())
    assert meta["status"] == "ok"
    assert meta["engine"] == "tesseract"
    assert meta["page_count"] == 2
    assert len(meta["pdf_sha256"]) == 64
    assert "started_at" in meta and "finished_at" in meta


def test_ocr_card_is_idempotent_when_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _pdf_card()
    out_dir = tmp_path / "ocr" / card.card_id
    out_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(json.dumps({"status": "ok"}))

    pdf_path = tmp_path / "src.pdf"
    _write_fake_pdf(pdf_path)

    # Engine should never be called.
    def boom(*_: object, **__: object) -> Iterator[object]:
        raise AssertionError("rasterize_pdf should not run when meta says done")

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", boom)

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300)
    assert did_work is False


def test_ocr_card_skips_when_pdf_missing(tmp_path: Path) -> None:
    card = _pdf_card()
    missing_pdf = tmp_path / "nope.pdf"
    out_dir = tmp_path / "ocr" / card.card_id

    did_work = ocr_card(card, missing_pdf, out_dir, dpi=300)
    assert did_work is False
    assert not out_dir.exists()


def test_ocr_card_records_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a page raises mid-OCR, status is 'failed' and the partial pages.jsonl stays."""

    def fake_rasterize(path: Path, dpi: int) -> Iterator[object]:
        yield object()
        yield object()

    calls = {"n": 0}

    def fake_ocr_image(_: object) -> tuple[str, float]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("tesseract crashed on page 2")
        return ("ok page", 90.0)

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(ocr_pipeline, "ocr_image", fake_ocr_image)

    card = _pdf_card()
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300)

    assert did_work is True  # we did try
    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["status"] == "failed"
    assert "tesseract crashed" in meta["error"]
    assert meta["page_count"] == 1  # the one that succeeded
