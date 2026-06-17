"""OCR pipeline: PDF → per-page text + confidence.

Per PDF, ``settings.ocr_dir/{card_id}/`` contains ``pages.jsonl`` (one
``{page, text, confidence, engine}`` per page) and ``meta.json`` (status,
engine, pdf hash/size, timestamps). Idempotent: a card with
``meta.json["status"] == "ok"`` is skipped on re-runs (use ``force=True``
to override).

The ``ocr_image`` seam is engine-agnostic — Tesseract (CPU, default), Surya
(GPU, in ``ocr/surya.py``), and the LLM fallback (``ocr/llm.py``) plug into
the same shape. ``engine="auto"`` runs the primary engine then re-OCRs any
page with confidence < ``settings.ocr_llm_threshold`` via the LLM.
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
from pursue_index.ocr import auto as ocr_auto
from pursue_index.ocr import dots as ocr_dots
from pursue_index.ocr import llm as ocr_llm
from pursue_index.ocr import runners as ocr_runners
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
    underlying seams (``ocr_pipeline.ocr_image`` / ``ocr_surya.ocr_image``
    / ``ocr_llm.ocr_image``).
    """
    if engine == "surya":
        return lambda img: ocr_surya.ocr_image(img)
    if engine == "tesseract":
        return lambda img: ocr_image(img)
    if engine == "llm":
        return lambda img: ocr_llm.ocr_image(img)
    if engine == "dots":
        return lambda img: ocr_dots.ocr_image(img)
    raise ValueError(f"Unknown OCR engine: {engine!r}")


def _rasterize(path: Path, dpi: int):  # type: ignore[no-untyped-def]
    """Indirected so tests can monkeypatch ``ocr_pipeline.rasterize_pdf``."""
    return rasterize_pdf(path, dpi)


def _run_engine(
    pdf_path: Path,
    pages_path: Path,
    dpi: int,
    engine: EngineName | None = None,
    primary_engine: EngineName | None = None,
) -> tuple[int, str | None]:
    """Stream pages.jsonl out of the engine. Returns (page_count, error_or_None)."""
    if engine is None:
        engine = _resolve_default_engine()
    if engine == "auto":
        chosen_primary = ocr_auto.resolve_primary_engine(primary_engine)
        run_primary = _engine_ocr_image(chosen_primary)
        return ocr_runners.run_auto_engine(
            pdf_path, pages_path, dpi, chosen_primary, run_primary, _rasterize
        )
    if engine == "llm-dots":
        return ocr_runners.run_llm_dots_fallback(pdf_path, pages_path, dpi, _rasterize)
    run_ocr = _engine_ocr_image(engine)
    return ocr_runners.run_single_engine(
        pdf_path, pages_path, dpi, engine, run_ocr, _rasterize
    )


def _resolve_meta_engine(engine: EngineName, primary_engine: EngineName | None) -> str:
    """Pick the ``meta.json`` ``engine`` value based on the run mode."""
    if engine != "auto":
        return engine
    chosen_primary = ocr_auto.resolve_primary_engine(primary_engine)
    return ocr_auto.auto_meta_engine(chosen_primary)


def _build_meta(
    card: CardMetadata,
    engine: EngineName,
    primary_engine: EngineName | None,
    pdf_bytes: bytes,
    page_count: int,
    started_at: datetime,
    finished_at: datetime,
    error: str | None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "card_id": card.card_id,
        "engine": _resolve_meta_engine(engine, primary_engine),
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
    return meta


def ocr_card(
    card: CardMetadata,
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 300,
    engine: EngineName | None = None,
    force: bool = False,
    primary_engine: EngineName | None = None,
) -> bool:
    """Run OCR over a PDF; write pages.jsonl + meta.json. Idempotent.

    Returns ``True`` if OCR ran (success or failure), ``False`` if skipped.
    The ``engine`` selects which adapter runs:

    - ``"tesseract"`` (default, CPU)
    - ``"surya"`` (GPU)
    - ``"llm"`` (Anthropic vision)
    - ``"auto"`` — run primary (``primary_engine`` or surya/tesseract via
      auto-detect), re-OCR low-confidence pages via the LLM fallback.

    ``force=True`` bypasses the ``meta.json`` idempotency check so a card
    with existing OCR output is re-processed. ``primary_engine`` only
    applies when ``engine="auto"``.
    """
    engine = engine or _resolve_default_engine()
    if not force and _is_done(out_dir):
        log.info("ocr.skip.done", card_id=card.card_id)
        return False
    if not pdf_path.exists():
        log.warning("ocr.skip.missing_pdf", card_id=card.card_id, path=str(pdf_path))
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    log.info("ocr.start", card_id=card.card_id, path=str(pdf_path), engine=engine)

    pdf_bytes = pdf_path.read_bytes()
    page_count, error = _run_engine(
        pdf_path, out_dir / "pages.jsonl", dpi, engine, primary_engine
    )
    meta = _build_meta(
        card, engine, primary_engine, pdf_bytes, page_count,
        started_at, datetime.now(UTC), error,
    )
    if error is not None:
        log.error("ocr.fail", card_id=card.card_id, error=error)
    _write_meta(out_dir / "meta.json", meta)

    log.info("ocr.done", card_id=card.card_id, pages=page_count, status=meta["status"])
    return True


def _resolve_default_engine() -> EngineName:
    """``PURSUE_OCR_ENGINE`` → engine name."""
    cfg = settings.ocr_engine
    return cfg if cfg in ("surya", "tesseract", "llm", "dots", "llm-dots", "auto") else DEFAULT_ENGINE


def _concurrency_for(engine: EngineName) -> int:
    """Engine-aware concurrency. LLM/auto parallelize via ``PURSUE_OCR_LLM_CONCURRENCY``
    (default 4 — Anthropic SDK handles its own retries); surya stays at 1
    (single GPU can't truly parallelize); tesseract caps at cpu_count."""
    if engine in ("llm", "auto", "llm-dots"):
        # llm-dots: llm calls parallelize like llm; the rare dots fallback
        # serializes on the worker lock (ocr.dots._lock), so card-level
        # concurrency is safe.
        return int(os.getenv("PURSUE_OCR_LLM_CONCURRENCY", "4"))
    if engine in ("surya", "dots"):
        # surya: single GPU. dots: a single persistent GPU worker with one
        # stdin/stdout channel — concurrent calls would interleave and corrupt
        # the line protocol.
        return 1
    return min(4, os.cpu_count() or 1)


async def ocr_all(
    manifest: Manifest,
    engine: EngineName | None = None,
    force: bool = False,
    concurrency: int | None = None,
) -> None:
    """OCR every PDF card in the manifest with bounded concurrency.

    Tesseract caps at ``min(4, cpu_count)``; surya stays at 1 (single GPU);
    LLM/auto default to ``PURSUE_OCR_LLM_CONCURRENCY`` (=4). ``concurrency``
    overrides everything when set — wired to ``pursue ocr run --concurrency``.
    ``force=True`` re-OCRs cards even if their ``meta.json`` says ``status=ok``.
    """
    chosen = engine or _resolve_default_engine()
    pdf_cards = [c for c in manifest.cards if c.asset_type == "PDF"]
    resolved_concurrency = concurrency if concurrency is not None else _concurrency_for(chosen)
    log.info(
        "ocr.start_all",
        pdf_cards=len(pdf_cards),
        engine=chosen,
        force=force,
        concurrency=resolved_concurrency,
    )

    sem = asyncio.Semaphore(resolved_concurrency)

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
                force,
            )

    await asyncio.gather(*(_bounded(c) for c in pdf_cards))
    log.info("ocr.done_all", pdf_cards=len(pdf_cards), engine=chosen)
