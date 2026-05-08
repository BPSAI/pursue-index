"""OCR pipeline: PDF → per-page text + confidence.

Per PDF, ``settings.ocr_dir/{card_id}/`` contains ``pages.jsonl`` (one
``{page, text, confidence, engine}`` per page) and ``meta.json`` (status,
engine, pdf hash/size, timestamps). Idempotent: a card with
``meta.json["status"] == "ok"`` is skipped on re-runs.

The ``ocr_image`` seam is engine-agnostic — Tesseract (CPU, default) and
Surya (GPU, in ``ocr/surya.py``) plug into the same shape.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.download.downloader import asset_path_for
from pursue_index.ocr import surya as ocr_surya
from pursue_index.scrape.types import CardMetadata, Manifest

log = get_logger(__name__)

EngineName = str
DEFAULT_ENGINE: EngineName = "tesseract"


def rasterize_pdf(path: Path, dpi: int) -> Iterator[Image.Image]:
    """Yield one PIL Image per PDF page, rendered at ``dpi`` DPI."""
    yield from convert_from_path(str(path), dpi=dpi)


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return ``(text, mean_word_confidence)`` for a single page image."""
    text = pytesseract.image_to_string(img)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    confidences = [int(c) for c in data["conf"] if str(c) != "-1"]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return text, mean_conf


def card_ocr_dir(card: CardMetadata) -> Path:
    """Where this card's OCR artifacts live."""
    return settings.ocr_dir / card.card_id


def _is_done(out_dir: Path) -> bool:
    meta_path = out_dir / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return False
    return meta.get("status") == "ok"


def _write_meta(meta_path: Path, meta: dict[str, object]) -> None:
    meta_path.write_text(json.dumps(meta, indent=2, default=str))


def _engine_ocr_image(engine: EngineName):  # type: ignore[no-untyped-def]
    """Look up the ``ocr_image(img) -> (text, conf)`` callable for ``engine``.

    Indirected via module attribute reads so tests can monkeypatch the
    underlying seams (``ocr_pipeline.ocr_image`` / ``ocr_surya.ocr_image``).
    """
    if engine == "surya":
        return lambda img: ocr_surya.ocr_image(img)
    if engine == "tesseract":
        return lambda img: ocr_image(img)
    raise ValueError(f"Unknown OCR engine: {engine!r}")


def _run_engine(
    pdf_path: Path,
    pages_path: Path,
    dpi: int,
    engine: EngineName = DEFAULT_ENGINE,
) -> tuple[int, str | None]:
    """Stream pages.jsonl out of the engine. Returns (page_count, error_or_None)."""
    page_count = 0
    run_ocr = _engine_ocr_image(engine)
    try:
        with pages_path.open("w") as fh:
            for page_idx, img in enumerate(rasterize_pdf(pdf_path, dpi), start=1):
                text, conf = run_ocr(img)
                fh.write(
                    json.dumps(
                        {
                            "page": page_idx,
                            "text": text,
                            "confidence": conf,
                            "engine": engine,
                        }
                    )
                    + "\n"
                )
                page_count += 1
    except Exception as exc:  # noqa: BLE001 — record any engine error in meta
        return page_count, f"{type(exc).__name__}: {exc}"
    return page_count, None


def ocr_card(
    card: CardMetadata,
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 300,
    engine: EngineName = DEFAULT_ENGINE,
) -> bool:
    """Run OCR over a PDF; write pages.jsonl + meta.json. Idempotent.

    Returns ``True`` if OCR ran (success or failure), ``False`` if skipped.
    The ``engine`` selects which adapter runs — ``"tesseract"`` (default,
    CPU) or ``"surya"`` (GPU). Both share the same output format; the
    ``engine`` field on each row + on ``meta.json`` records which ran.
    """
    if _is_done(out_dir):
        log.info("ocr.skip.done", card_id=card.card_id)
        return False
    if not pdf_path.exists():
        log.warning("ocr.skip.missing_pdf", card_id=card.card_id, path=str(pdf_path))
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    log.info("ocr.start", card_id=card.card_id, path=str(pdf_path), engine=engine)

    pdf_bytes = pdf_path.read_bytes()
    page_count, error = _run_engine(pdf_path, out_dir / "pages.jsonl", dpi, engine)
    finished_at = datetime.now(UTC)

    meta: dict[str, object] = {
        "card_id": card.card_id,
        "engine": engine,
        "status": "ok" if error is None else "failed",
        "page_count": page_count,
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "pdf_bytes": len(pdf_bytes),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
    }
    if error is not None:
        meta["error"] = error
        log.error("ocr.fail", card_id=card.card_id, error=error)
    _write_meta(out_dir / "meta.json", meta)

    log.info("ocr.done", card_id=card.card_id, pages=page_count, status=meta["status"])
    return True


def _resolve_default_engine() -> EngineName:
    """``PURSUE_OCR_ENGINE`` → engine name. ``"auto"``/``"azure"`` → tesseract."""
    cfg = settings.ocr_engine
    return cfg if cfg in ("surya", "tesseract") else DEFAULT_ENGINE


async def ocr_all(manifest: Manifest, engine: EngineName | None = None) -> None:
    """OCR every PDF card in the manifest with bounded concurrency.

    Tesseract is CPU-bound: cap at ``min(4, cpu_count)``. Surya is GPU-bound:
    serialize cards and let Surya batch internally.
    """
    chosen = engine or _resolve_default_engine()
    pdf_cards = [c for c in manifest.cards if c.asset_type == "PDF"]
    log.info("ocr.start_all", pdf_cards=len(pdf_cards), engine=chosen)

    concurrency = 1 if chosen == "surya" else min(4, os.cpu_count() or 1)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(card: CardMetadata) -> None:
        pdf_path = asset_path_for(card)
        if pdf_path is None:
            log.warning("ocr.skip.no_path", card_id=card.card_id)
            return
        async with sem:
            await asyncio.to_thread(
                ocr_card,
                card,
                pdf_path,
                card_ocr_dir(card),
                settings.ocr_dpi,
                chosen,
            )

    await asyncio.gather(*(_bounded(c) for c in pdf_cards))
    log.info("ocr.done_all", pdf_cards=len(pdf_cards), engine=chosen)
