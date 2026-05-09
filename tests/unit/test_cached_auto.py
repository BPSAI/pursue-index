"""Tests for cache-aware auto-mode OCR.

When a card's existing ``pages.jsonl`` already holds full primary-engine
output (e.g. a prior Surya pass), the auto-mode upgrade path should
re-use those rows verbatim and only invoke the LLM fallback on the
sub-threshold pages — not re-rasterize and re-OCR the whole PDF.

This is the surgical-recovery path used to apply the LLM cleanup pass on
top of the existing 116-card Surya corpus without spending another
~3-4h re-running Surya from scratch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pursue_index.ocr import cached_auto


def _write_pages_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_no_low_conf_pages_is_a_noop(tmp_path: Path) -> None:
    """If every page is above threshold, no LLM calls and pages.jsonl unchanged."""
    pages = tmp_path / "pages.jsonl"
    _write_pages_jsonl(
        pages,
        [
            {"page": 1, "text": "high1", "confidence": 90.0, "engine": "surya"},
            {"page": 2, "text": "high2", "confidence": 85.0, "engine": "surya"},
        ],
    )
    calls: list[int] = []

    def _fake_render_page(_pdf: Path, _page_idx: int, _dpi: int) -> Image.Image:
        calls.append(_page_idx)
        return Image.new("RGB", (10, 10))

    def _fake_llm(_img: Image.Image) -> tuple[str, float]:
        raise AssertionError("LLM should not be called when all pages above threshold")

    rewrote, llm_calls = cached_auto.upgrade_pages_jsonl(
        pages_path=pages,
        pdf_path=tmp_path / "fake.pdf",
        primary_engine="surya",
        threshold=70.0,
        render_page=_fake_render_page,
        llm_ocr=_fake_llm,
        dpi=300,
    )

    assert rewrote is False
    assert llm_calls == 0
    assert calls == []


def test_low_conf_pages_get_llm_with_primary_preserved(tmp_path: Path) -> None:
    """Sub-threshold pages get LLM output; primary block is preserved."""
    pages = tmp_path / "pages.jsonl"
    _write_pages_jsonl(
        pages,
        [
            {"page": 1, "text": "high", "confidence": 90.0, "engine": "surya"},
            {"page": 2, "text": "garbled-low-conf", "confidence": 40.0, "engine": "surya"},
        ],
    )
    rendered: list[int] = []

    def _fake_render(_pdf: Path, page_idx: int, _dpi: int) -> Image.Image:
        rendered.append(page_idx)
        return Image.new("RGB", (10, 10))

    def _fake_llm(_img: Image.Image) -> tuple[str, float]:
        return ("clean transcription", 88.0)

    rewrote, llm_calls = cached_auto.upgrade_pages_jsonl(
        pages_path=pages,
        pdf_path=tmp_path / "fake.pdf",
        primary_engine="surya",
        threshold=70.0,
        render_page=_fake_render,
        llm_ocr=_fake_llm,
        dpi=300,
    )

    assert rewrote is True
    assert llm_calls == 1
    assert rendered == [2]

    rows = [json.loads(line) for line in pages.read_text().splitlines() if line.strip()]
    assert len(rows) == 2

    # Page 1 unchanged
    assert rows[0] == {"page": 1, "text": "high", "confidence": 90.0, "engine": "surya"}

    # Page 2: LLM replaces top-level text/confidence/engine; primary preserved.
    assert rows[1]["page"] == 2
    assert rows[1]["text"] == "clean transcription"
    assert rows[1]["confidence"] == 88.0
    assert rows[1]["engine"] == "llm-anthropic"
    assert rows[1]["primary"] == {
        "engine": "surya",
        "text": "garbled-low-conf",
        "confidence": 40.0,
    }


def test_skips_rows_already_upgraded(tmp_path: Path) -> None:
    """Rows that already have a ``primary`` block are not re-upgraded."""
    pages = tmp_path / "pages.jsonl"
    _write_pages_jsonl(
        pages,
        [
            {
                "page": 1,
                "text": "already-llm-cleaned",
                "confidence": 92.0,
                "engine": "llm-anthropic",
                "primary": {"engine": "surya", "text": "old", "confidence": 30.0},
            },
        ],
    )

    def _fake_render(_pdf: Path, _page_idx: int, _dpi: int) -> Image.Image:
        raise AssertionError("should not render — row already upgraded")

    def _fake_llm(_img: Image.Image) -> tuple[str, float]:
        raise AssertionError("should not call LLM — row already upgraded")

    rewrote, llm_calls = cached_auto.upgrade_pages_jsonl(
        pages_path=pages,
        pdf_path=tmp_path / "fake.pdf",
        primary_engine="surya",
        threshold=70.0,
        render_page=_fake_render,
        llm_ocr=_fake_llm,
        dpi=300,
    )

    assert rewrote is False
    assert llm_calls == 0
