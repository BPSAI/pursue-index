"""Tests for auto-mode (primary engine + LLM fallback) and the ``--force`` flag.

The primary OCR engine and the LLM fallback are both stubbed at their seams
(``ocr_pipeline.ocr_image``, ``ocr_surya.ocr_image``, ``ocr_llm.ocr_image``)
so these tests run anywhere — no Tesseract / Surya / Anthropic dependency.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pursue_index.ocr import llm as ocr_llm
from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.ocr import surya as ocr_surya
from pursue_index.ocr.pipeline import ocr_card
from pursue_index.scrape.types import CardMetadata


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pdf_card(card_id: str = "auto000000000001") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title="Auto Test",
        asset_type="PDF",
        agency="FBI",
        asset_url=f"https://www.war.gov/medialink/ufo/{card_id}.pdf",
        asset_filename=f"{card_id}.pdf",
    )


def _write_fake_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake\n")


def _stub_engines(
    monkeypatch: pytest.MonkeyPatch,
    primary_pages: list[tuple[str, float]],
    llm_pages: list[tuple[str, float]],
    primary_engine: str = "tesseract",
) -> dict[str, list[Any]]:
    """Stub rasterize_pdf + the primary engine + the LLM fallback.

    Returns a counter dict for assertions: ``{"primary": [...], "llm": [...]}``.
    """

    def fake_rasterize(path: Path, dpi: int) -> Iterator[object]:
        for _ in primary_pages:
            yield object()

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", fake_rasterize)

    primary_iter = iter(primary_pages)
    llm_iter = iter(llm_pages)
    counter: dict[str, list[Any]] = {"primary": [], "llm": []}

    def fake_primary_tess(_: object) -> tuple[str, float]:
        result = next(primary_iter)
        counter["primary"].append(result)
        return result

    def fake_primary_surya(_: object) -> tuple[str, float]:
        result = next(primary_iter)
        counter["primary"].append(result)
        return result

    def fake_llm(_: object) -> tuple[str, float]:
        result = next(llm_iter)
        counter["llm"].append(result)
        return result

    if primary_engine == "tesseract":
        monkeypatch.setattr(ocr_pipeline, "ocr_image", fake_primary_tess)
    elif primary_engine == "surya":
        monkeypatch.setattr(ocr_surya, "ocr_image", fake_primary_surya)

    monkeypatch.setattr(ocr_llm, "ocr_image", fake_llm)
    return counter


# ---------------------------------------------------------------------------
# auto mode: low confidence triggers LLM fallback
# ---------------------------------------------------------------------------
def test_auto_low_conf_page_triggers_llm_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pages below the threshold are re-OCR'd via the LLM; high-conf pages aren't."""
    monkeypatch.setattr(ocr_pipeline.settings, "ocr_llm_threshold", 70.0)

    counter = _stub_engines(
        monkeypatch,
        primary_pages=[
            ("garbage", 27.0),     # below threshold → re-OCR
            ("clean text", 92.0),  # above threshold → keep
        ],
        llm_pages=[("VERBATIM RECOVERED TEXT", 88.0)],
    )

    card = _pdf_card()
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    did_work = ocr_card(
        card, pdf_path, out_dir, dpi=300, engine="auto", primary_engine="tesseract"
    )
    assert did_work is True

    # Primary ran on both pages; LLM ran on the one low-confidence page only
    assert len(counter["primary"]) == 2
    assert len(counter["llm"]) == 1

    rows = [
        json.loads(line) for line in (out_dir / "pages.jsonl").read_text().splitlines()
    ]
    # Page 1: LLM result wins, but primary's attempt is preserved as a sibling
    assert rows[0]["page"] == 1
    assert rows[0]["text"] == "VERBATIM RECOVERED TEXT"
    assert rows[0]["confidence"] == pytest.approx(88.0)
    assert rows[0]["engine"] == "llm-anthropic"
    assert rows[0]["primary"]["engine"] == "tesseract"
    assert rows[0]["primary"]["text"] == "garbage"
    assert rows[0]["primary"]["confidence"] == pytest.approx(27.0)

    # Page 2: high confidence, no LLM fallback recorded
    assert rows[1]["page"] == 2
    assert rows[1]["text"] == "clean text"
    assert rows[1]["engine"] == "tesseract"
    assert "primary" not in rows[1]

    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["status"] == "ok"
    # auto:{primary}+{fallback} so the audit trail shows what actually ran
    assert meta["engine"] == "auto:tesseract+llm-anthropic"


def test_auto_all_high_conf_skips_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If every page is above threshold, the LLM is never called."""
    monkeypatch.setattr(ocr_pipeline.settings, "ocr_llm_threshold", 70.0)

    counter = _stub_engines(
        monkeypatch,
        primary_pages=[("clean A", 90.0), ("clean B", 95.0)],
        llm_pages=[],  # never consumed
    )

    card = _pdf_card("auto000000000002")
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    ocr_card(
        card, pdf_path, out_dir, dpi=300, engine="auto", primary_engine="tesseract"
    )

    assert len(counter["llm"]) == 0
    rows = [
        json.loads(line) for line in (out_dir / "pages.jsonl").read_text().splitlines()
    ]
    for row in rows:
        assert row["engine"] == "tesseract"
        assert "primary" not in row


def test_auto_with_surya_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``primary_engine='surya'`` routes the primary call through the Surya seam."""
    monkeypatch.setattr(ocr_pipeline.settings, "ocr_llm_threshold", 70.0)

    counter = _stub_engines(
        monkeypatch,
        primary_pages=[("surya garbage", 30.0)],
        llm_pages=[("LLM clean recovery", 91.0)],
        primary_engine="surya",
    )

    card = _pdf_card("auto000000000003")
    pdf_path = tmp_path / "src.pdf"
    out_dir = tmp_path / "ocr" / card.card_id
    _write_fake_pdf(pdf_path)

    ocr_card(card, pdf_path, out_dir, dpi=300, engine="auto", primary_engine="surya")

    rows = [
        json.loads(line) for line in (out_dir / "pages.jsonl").read_text().splitlines()
    ]
    assert rows[0]["engine"] == "llm-anthropic"
    assert rows[0]["primary"]["engine"] == "surya"
    assert len(counter["llm"]) == 1

    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["engine"] == "auto:surya+llm-anthropic"


# ---------------------------------------------------------------------------
# --force: bypasses _is_done idempotency
# ---------------------------------------------------------------------------
def test_force_reruns_card_with_existing_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``force=True`` re-OCRs even when meta.json says status=ok."""
    card = _pdf_card("force0000000001")
    out_dir = tmp_path / "ocr" / card.card_id
    out_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(
        json.dumps({"status": "ok", "engine": "tesseract", "page_count": 999})
    )

    pdf_path = tmp_path / "src.pdf"
    _write_fake_pdf(pdf_path)

    counter = _stub_engines(
        monkeypatch,
        primary_pages=[("re-ocr'd page", 80.0)],
        llm_pages=[],
    )

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300, engine="tesseract", force=True)
    assert did_work is True
    assert len(counter["primary"]) == 1

    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["page_count"] == 1, "meta should reflect the re-OCR run, not stale 999"


def test_no_force_still_skips_done_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default behavior (no force) preserves the existing idempotency check."""
    card = _pdf_card("force0000000002")
    out_dir = tmp_path / "ocr" / card.card_id
    out_dir.mkdir(parents=True)
    (out_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    pdf_path = tmp_path / "src.pdf"
    _write_fake_pdf(pdf_path)

    def boom(*_: object, **__: object) -> Iterator[object]:
        raise AssertionError("rasterize_pdf should not run when not forced")

    monkeypatch.setattr(ocr_pipeline, "rasterize_pdf", boom)

    did_work = ocr_card(card, pdf_path, out_dir, dpi=300, engine="tesseract")
    assert did_work is False
