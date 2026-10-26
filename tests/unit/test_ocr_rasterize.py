"""Tests for streaming, page-at-a-time PDF rasterization.

``rasterize_pdf`` used to call ``convert_from_path(path, dpi)`` with no page
bounds, which renders every page into memory before yielding the first one —
memory scales with document length (Release 7 hit 40.9 GB peak RSS on a
298-page document at concurrency 4). It must instead read the page count
once and render each page individually via ``first_page``/``last_page``, so
at most one rendered page is ever live per call.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pdf2image import convert_from_path as real_convert_from_path

from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.ocr import runners as ocr_runners
from pursue_index.ocr.pipeline import ocr_card
from pursue_index.scrape.types import CardMetadata, Manifest

THREE_PAGE_PDF = Path(__file__).parent.parent / "fixtures" / "ocr_three_page.pdf"


def _pdf_card(card_id: str = "abc1234567890def") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="Test Card",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


# ---------------------------------------------------------------------------
# AC: never more than one rendered page live at a time
# ---------------------------------------------------------------------------


class _FakeImage:
    live = 0
    max_live = 0

    def __init__(self) -> None:
        _FakeImage.live += 1
        _FakeImage.max_live = max(_FakeImage.max_live, _FakeImage.live)

    def __del__(self) -> None:
        _FakeImage.live -= 1


def _reset_fake_image() -> None:
    _FakeImage.live = 0
    _FakeImage.max_live = 0


def test_rasterize_pdf_never_holds_more_than_one_rendered_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 50-page fixture, consumed one page at a time, never has more than one
    fake image alive — the rasterizer itself must not pre-render ahead."""
    _reset_fake_image()
    page_count = 50

    def fake_pdfinfo(path: str, **kwargs: Any) -> dict[str, object]:
        return {"Pages": page_count}

    def fake_convert(
        path: str,
        dpi: int = 200,
        first_page: int | None = None,
        last_page: int | None = None,
        **kwargs: Any,
    ) -> list[_FakeImage]:
        assert first_page is not None and first_page == last_page, (
            "must request exactly one page per render call, "
            f"got first_page={first_page} last_page={last_page}"
        )
        return [_FakeImage()]

    monkeypatch.setattr(ocr_pipeline, "pdfinfo_from_path", fake_pdfinfo)
    monkeypatch.setattr(ocr_pipeline, "convert_from_path", fake_convert)

    gen = ocr_pipeline.rasterize_pdf(Path("fake.pdf"), dpi=150)
    seen = 0
    img: object | None = next(gen)
    while img is not None:
        seen += 1
        assert _FakeImage.live <= 1, f"{_FakeImage.live} pages live at once"
        img = None  # consumer releases the page before requesting the next one
        img = next(gen, None)

    assert seen == page_count
    assert _FakeImage.max_live <= 1


def test_rasterize_pdf_renders_pages_in_order_against_a_real_pdf() -> None:
    """Against a real multi-page PDF, streaming rasterization yields pages in
    the same order and with the same pixels as a single whole-document call."""
    expected = real_convert_from_path(str(THREE_PAGE_PDF), dpi=72)
    actual = list(ocr_pipeline.rasterize_pdf(THREE_PAGE_PDF, dpi=72))

    assert len(actual) == len(expected) == 3
    for exp_img, act_img in zip(expected, actual, strict=True):
        assert exp_img.size == act_img.size
        assert exp_img.tobytes() == act_img.tobytes()


# ---------------------------------------------------------------------------
# AC: pages.jsonl output is unchanged for a 3-page fixture
# ---------------------------------------------------------------------------


def _deterministic_ocr_stub() -> Any:
    """A page-count-keyed OCR stub so reference/actual runs agree regardless
    of which image object (sizes differ per page) is passed in."""
    counter = {"n": 0}

    def _ocr(img: object) -> tuple[str, float]:
        counter["n"] += 1
        return (f"page text {counter['n']}", 80.0 + counter["n"])

    return _ocr


def _whole_document_rasterize(path: Path, dpi: int) -> Any:
    """The old behavior: one ``convert_from_path`` call over the whole doc."""
    return iter(real_convert_from_path(str(path), dpi=dpi))


def test_pages_jsonl_byte_identical_to_whole_document_rasterization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = _pdf_card()
    out_dir = tmp_path / "ocr" / card.card_id

    monkeypatch.setattr(ocr_pipeline, "ocr_image", _deterministic_ocr_stub())
    did_work = ocr_card(card, THREE_PAGE_PDF, out_dir, dpi=72, engine="tesseract")
    assert did_work is True
    actual = (out_dir / "pages.jsonl").read_text()

    expected_path = tmp_path / "expected_pages.jsonl"
    ocr_runners.run_single_engine(
        THREE_PAGE_PDF,
        expected_path,
        dpi=72,
        engine="tesseract",
        run_ocr=_deterministic_ocr_stub(),
        rasterize=_whole_document_rasterize,
    )
    expected = expected_path.read_text()

    assert actual == expected
    rows = [json.loads(line) for line in actual.splitlines()]
    assert [r["page"] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# AC: peak RSS surfaces in the run summary
# ---------------------------------------------------------------------------


def test_peak_rss_mb_returns_a_positive_float() -> None:
    value = ocr_runners.peak_rss_mb()
    assert isinstance(value, float)
    assert value > 0


def test_done_all_summary_includes_peak_rss_mb() -> None:
    summary = ocr_runners.done_all_summary(
        pdf_cards=5, engine="llm-dots", peak_rss_mb=123.456
    )
    assert summary["pdf_cards"] == 5
    assert summary["engine"] == "llm-dots"
    assert summary["peak_rss_mb"] == pytest.approx(123.5)


def test_ocr_all_logs_peak_rss_mb_in_the_done_all_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr_all``'s final summary log line carries ``peak_rss_mb``."""
    monkeypatch.setattr(ocr_runners, "peak_rss_mb", lambda: 123.4)
    captured: list[dict[str, Any]] = []

    def fake_log(event: str, **kw: Any) -> None:
        captured.append({"event": event, **kw})

    monkeypatch.setattr(ocr_pipeline.log, "info", fake_log)

    manifest = Manifest(
        source_url="https://example.com/x.csv",
        fetched_at="2026-05-22T00:00:00Z",
        csv_sha256="0" * 64,
        cards=[],
    )
    asyncio.run(ocr_pipeline.ocr_all(manifest, engine="llm"))

    done_events = [e for e in captured if e["event"] == "ocr.done_all"]
    assert done_events, f"expected an ocr.done_all event, got: {captured}"
    assert done_events[0]["peak_rss_mb"] == 123.4
