"""Tests for ``model`` / ``engine_version`` on OCR page rows (R7C.16 / #171).

OCR sidecar rows recorded ``engine`` (``llm``/``dots``) but not the model
that produced the text, so verifying which model OCR'd a page meant
reconstructing it from run-time settings, which can drift. These tests
prove the resolved model id lands on every ``llm`` row and the dots build
identifier lands on every ``dots`` row, at the ``ocr.runners`` seam that
writes ``pages.jsonl``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from pursue_index.config import settings
from pursue_index.ocr import dots as ocr_dots
from pursue_index.ocr import runners as ocr_runners
from pursue_index.ocr.llm import ContentFilterError


def _rasterize(n: int):
    def fake(path: Path, dpi: int) -> Iterator[object]:
        for _ in range(n):
            yield object()

    return fake


def test_llm_engine_rows_carry_the_resolved_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ocr_llm_model", "claude-test-model")
    replies = iter([("p1", 90.0), ("p2", 91.0)])
    pages_path = tmp_path / "pages.jsonl"

    page_count, error = ocr_runners.run_single_engine(
        tmp_path / "src.pdf",
        pages_path,
        300,
        "llm",
        lambda _img: next(replies),
        _rasterize(2),
    )

    assert error is None
    assert page_count == 2
    rows = [json.loads(line) for line in pages_path.read_text().splitlines()]
    for row in rows:
        assert row["engine"] == "llm"
        assert row["model"] == "claude-test-model"


def test_dots_engine_rows_carry_the_engine_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PURSUE_DOTS_MODEL", "/models/dots-mocr-v3")
    pages_path = tmp_path / "pages.jsonl"

    page_count, error = ocr_runners.run_single_engine(
        tmp_path / "src.pdf",
        pages_path,
        300,
        "dots",
        lambda _img: ("dots text", 70.0),
        _rasterize(1),
    )

    assert error is None
    assert page_count == 1
    rows = [json.loads(line) for line in pages_path.read_text().splitlines()]
    assert rows[0]["engine"] == "dots"
    assert rows[0]["engine_version"] == "dots-mocr-v3"
    assert "model" not in rows[0]


def test_tesseract_rows_carry_neither_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retired engine has no 'operated model' concept — no new fields."""
    pages_path = tmp_path / "pages.jsonl"

    ocr_runners.run_single_engine(
        tmp_path / "src.pdf",
        pages_path,
        300,
        "tesseract",
        lambda _img: ("tess text", 80.0),
        _rasterize(1),
    )

    row = json.loads(pages_path.read_text().splitlines()[0])
    assert "model" not in row
    assert "engine_version" not in row


def test_llm_dots_fallback_records_model_on_llm_rows_and_version_on_dots_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake LLM client that content-filters page 1 falls back to dots for
    that page only; page 2 stays on the (fake) LLM. Each row carries the
    provenance field for whichever engine actually produced it."""
    monkeypatch.setattr(settings, "ocr_llm_model", "claude-test-model")
    monkeypatch.setenv("PURSUE_DOTS_MODEL", "/models/dots-mocr-v3")

    llm_calls = {"n": 0}

    def fake_llm_ocr_image(_img: object) -> tuple[str, float]:
        llm_calls["n"] += 1
        if llm_calls["n"] == 1:
            raise ContentFilterError("Output blocked by content filtering policy")
        return "p2 llm text", 91.0

    monkeypatch.setattr(ocr_runners.ocr_llm, "ocr_image", fake_llm_ocr_image)
    monkeypatch.setattr(ocr_dots, "ocr_image", lambda _img: ("p1 dots text", 70.0))

    pages_path = tmp_path / "pages.jsonl"
    page_count, error = ocr_runners.run_llm_dots_fallback(
        tmp_path / "src.pdf", pages_path, 300, _rasterize(2)
    )

    assert error is None
    assert page_count == 2
    rows = [json.loads(line) for line in pages_path.read_text().splitlines()]

    assert rows[0]["engine"] == "dots"
    assert rows[0]["engine_version"] == "dots-mocr-v3"
    assert "model" not in rows[0]

    assert rows[1]["engine"] == "llm"
    assert rows[1]["model"] == "claude-test-model"
    assert "engine_version" not in rows[1]
