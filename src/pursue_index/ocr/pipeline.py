"""OCR pipeline: PDF → per-page text + confidence (Tesseract v1).

Output convention, per PDF::

    settings.ocr_dir / {card_id} /
        pages.jsonl   # one JSON object per page: {page, text, confidence, engine}
        meta.json     # status, engine, pdf hash/size, run timestamps

Idempotent: a card with ``meta.json["status"] == "ok"`` is skipped on
re-runs. A partial failure leaves ``status == "failed"`` so the next run
will retry. Azure DI fallback is intentionally out of scope for v1; the
``ocr_image`` seam is engine-agnostic so it can land later without
disturbing the orchestration.
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
from pursue_index.scrape.types import CardMetadata, Manifest

log = get_logger(__name__)


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


def _run_engine(pdf_path: Path, pages_path: Path, dpi: int) -> tuple[int, str | None]:
    """Stream pages.jsonl out of the engine. Returns (page_count, error_or_None)."""
    page_count = 0
    try:
        with pages_path.open("w") as fh:
            for page_idx, img in enumerate(rasterize_pdf(pdf_path, dpi), start=1):
                text, conf = ocr_image(img)
                fh.write(
                    json.dumps(
                        {
                            "page": page_idx,
                            "text": text,
                            "confidence": conf,
                            "engine": "tesseract",
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
) -> bool:
    """Run Tesseract over a PDF; write pages.jsonl + meta.json. Idempotent.

    Returns ``True`` if OCR ran (success or failure), ``False`` if skipped.
    """
    if _is_done(out_dir):
        log.info("ocr.skip.done", card_id=card.card_id)
        return False
    if not pdf_path.exists():
        log.warning("ocr.skip.missing_pdf", card_id=card.card_id, path=str(pdf_path))
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    log.info("ocr.start", card_id=card.card_id, path=str(pdf_path))

    pdf_bytes = pdf_path.read_bytes()
    page_count, error = _run_engine(pdf_path, out_dir / "pages.jsonl", dpi)
    finished_at = datetime.now(UTC)

    meta: dict[str, object] = {
        "card_id": card.card_id,
        "engine": "tesseract",
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


async def ocr_all(manifest: Manifest) -> None:
    """OCR every PDF card in the manifest with bounded concurrency.

    Tesseract is CPU-bound; we cap concurrency at ``min(4, cpu_count)`` and
    run each card in a thread so we don't block the event loop.
    """
    pdf_cards = [c for c in manifest.cards if c.asset_type == "PDF"]
    log.info("ocr.start_all", pdf_cards=len(pdf_cards))

    concurrency = min(4, os.cpu_count() or 1)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(card: CardMetadata) -> None:
        pdf_path = asset_path_for(card)
        if pdf_path is None:
            log.warning("ocr.skip.no_path", card_id=card.card_id)
            return
        async with sem:
            await asyncio.to_thread(
                ocr_card, card, pdf_path, card_ocr_dir(card), settings.ocr_dpi
            )

    await asyncio.gather(*(_bounded(c) for c in pdf_cards))
    log.info("ocr.done_all", pdf_cards=len(pdf_cards))
