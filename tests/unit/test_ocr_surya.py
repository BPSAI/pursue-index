"""Tests for the Surya OCR engine adapter.

These tests stub out the actual GPU model — they exercise the adapter's
contract (`ocr_image(img) -> (text, confidence)`) and the routing of
``engine="surya"`` through the existing pipeline orchestration.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.ocr import surya as ocr_surya
from pursue_index.ocr.pipeline import ocr_card
from pursue_index.scrape.types import CardMetadata


# ---------------------------------------------------------------------------
# fixtures + helpers
# ---------------------------------------------------------------------------
def _pdf_card(card_id: str = "surya000000000001") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="Surya Test Card",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def _write_fake_pdf(path: Path, content: bytes = b"%PDF-1.4 fake\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class _FakeTextLine:
    """Duck-typed stand-in for ``surya.recognition.TextLine``."""

    def __init__(self, text: str, confidence: float | None) -> None:
        self.text = text
        self.confidence = confidence


class _FakeOCRResult:
    """Duck-typed stand-in for ``surya.recognition.OCRResult``."""

    def __init__(self, text_lines: list[_FakeTextLine]) -> None:
        self.text_lines = text_lines


class _FakePredictor:
    """Stub for ``RecognitionPredictor`` — captures calls, returns canned results."""

    def __init__(self, results_per_call: list[list[_FakeTextLine]]) -> None:
        self._queue = list(results_per_call)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, images, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"n_images": len(images), "kwargs": kwargs})
        page_lines = self._queue.pop(0)
        return [_FakeOCRResult(page_lines)]


def _patch_surya_predictor(
    monkeypatch: pytest.MonkeyPatch, predictor: _FakePredictor
) -> None:
    """Force ``ocr_surya._get_predictor`` to return our stub."""
    monkeypatch.setattr(ocr_surya, "_get_predictor", lambda: predictor)


# ---------------------------------------------------------------------------
# ocr_image contract
# ---------------------------------------------------------------------------
def test_surya_ocr_image_joins_lines_and_returns_mean_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pred = _FakePredictor(
        [
            [
                _FakeTextLine("Hello world", 0.95),
                _FakeTextLine("from Surya", 0.85),
            ]
        ]
    )
    _patch_surya_predictor(monkeypatch, pred)

    img = Image.new("RGB", (10, 10))
    text, conf = ocr_surya.ocr_image(img)

    assert text == "Hello world\nfrom Surya"
    # Tesseract reports 0..100; Surya is 0..1 — adapter scales to match
    assert conf == pytest.approx(90.0)
    assert pred.calls and pred.calls[0]["n_images"] == 1


def test_surya_ocr_image_empty_page_returns_zero_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pred = _FakePredictor([[]])
    _patch_surya_predictor(monkeypatch, pred)

    img = Image.new("RGB", (10, 10))
    text, conf = ocr_surya.ocr_image(img)

    assert text == ""
    assert conf == 0.0


def test_surya_ocr_image_skips_none_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lines with ``confidence=None`` are still kept for text but skipped from the mean."""
    pred = _FakePredictor(
        [
            [
                _FakeTextLine("good line", 0.80),
                _FakeTextLine("missing conf", None),
            ]
        ]
    )
    _patch_surya_predictor(monkeypatch, pred)

    img = Image.new("RGB", (10, 10))
    text, conf = ocr_surya.ocr_image(img)

    assert text == "good line\nmissing conf"
    assert conf == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# routing through ocr_card
# ---------------------------------------------------------------------------
def _patch_engine_routing(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[tuple[str, float]],
) -> None:
    """Stub rasterize_pdf to yield N pages and the surya seam to return canned results."""

    def fake_rasterize(path: Path, dpi: int) -> Iterator[object]:
        for _ in pages:
            yield object()

    results = iter(pages)

    def fake_surya_ocr(_: object) -> tuple[str, float]:
        return next(results)

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(ocr_surya, "ocr_image", fake_surya_ocr)


def test_ocr_card_with_surya_engine_writes_surya_in_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_engine_routing(
        monkeypatch, [("Surya page 1", 91.0), ("Surya page 2", 87.5)]
    )

    card = _pdf_card()
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300, engine="surya")

    assert did_work is True
    rows = [
        json.loads(line)
        for line in (out_dir / "pages.jsonl").read_text().splitlines()
    ]
    assert [r["page"] for r in rows] == [1, 2]
    assert rows[0]["text"] == "Surya page 1"
    assert rows[0]["confidence"] == pytest.approx(91.0)
    assert all(r["engine"] == "surya" for r in rows)

    meta: dict[str, Any] = json.loads((out_dir / "meta.json").read_text())
    assert meta["engine"] == "surya"
    assert meta["status"] == "ok"
    assert meta["page_count"] == 2


def test_ocr_card_default_engine_still_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default engine remains tesseract when caller doesn't pass ``engine``."""

    def fake_rasterize(path: Path, dpi: int) -> Iterator[object]:
        yield object()

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", fake_rasterize)
    monkeypatch.setattr(
        ocr_pipeline, "ocr_image", lambda _: ("Tesseract page", 80.0)
    )

    card = _pdf_card("tesseract00000001")
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    ocr_card(card, pdf_path, out_dir, dpi=300)

    rows = [
        json.loads(line)
        for line in (out_dir / "pages.jsonl").read_text().splitlines()
    ]
    assert rows[0]["engine"] == "tesseract"
    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["engine"] == "tesseract"
