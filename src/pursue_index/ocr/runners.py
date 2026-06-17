"""Per-page engine runners that stream rows into ``pages.jsonl``.

Split out of ``pipeline.py`` to keep the orchestration module under the
function-count limit. The runners take a callable resolved by
``pipeline._engine_ocr_image`` so tests can monkeypatch the engine seams
(``ocr_pipeline.ocr_image`` / ``ocr_surya.ocr_image`` / ``ocr_llm.ocr_image``)
without touching this module.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.ocr import auto as ocr_auto
from pursue_index.ocr import dots as ocr_dots
from pursue_index.ocr import llm as ocr_llm
from pursue_index.ocr.llm import ContentFilterError

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

OCRFn = Callable[[Image.Image], tuple[str, float]]
PageIter = Callable[[Path, int], "object"]  # returns Iterator[Image]


def run_single_engine(
    pdf_path: Path,
    pages_path: Path,
    dpi: int,
    engine: str,
    run_ocr: OCRFn,
    rasterize: PageIter,
) -> tuple[int, str | None]:
    """Run one engine across every page; return ``(page_count, error_or_None)``."""
    page_count = 0
    try:
        with pages_path.open("w") as fh:
            for page_idx, img in enumerate(rasterize(pdf_path, dpi), start=1):
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
    except Exception as exc:
        return page_count, f"{type(exc).__name__}: {exc}"
    return page_count, None


def run_llm_dots_fallback(
    pdf_path: Path,
    pages_path: Path,
    dpi: int,
    rasterize: PageIter,
) -> tuple[int, str | None]:
    """LLM (Sonnet) per page; on Anthropic's content-filter 400, fall back to
    the local dots.mocr backstop for THAT page — no card abort.

    Per-page ``engine`` tag is ``llm`` normally, ``dots`` for a filter-blocked
    page, so a mixed doc (e.g. one sensitive page in an otherwise-clean card)
    keeps Sonnet everywhere except the blocked page. Other (non-filter) errors
    still propagate and fail the card, as before.
    """
    page_count = 0
    fallback_pages = 0
    try:
        with pages_path.open("w") as fh:
            for page_idx, img in enumerate(rasterize(pdf_path, dpi), start=1):
                try:
                    text, conf = ocr_llm.ocr_image(img)
                    engine = "llm"
                except ContentFilterError:
                    log.warning("ocr.llm_dots.fallback", page=page_idx)
                    text, conf = ocr_dots.ocr_image(img)
                    engine = "dots"
                    fallback_pages += 1
                fh.write(
                    json.dumps(
                        {"page": page_idx, "text": text, "confidence": conf, "engine": engine}
                    )
                    + "\n"
                )
                page_count += 1
    except Exception as exc:
        return page_count, f"{type(exc).__name__}: {exc}"
    if fallback_pages:
        log.info("ocr.llm_dots.done", pages=page_count, dots_fallback=fallback_pages)
    return page_count, None


def run_auto_engine(
    pdf_path: Path,
    pages_path: Path,
    dpi: int,
    primary_engine: str,
    run_primary: OCRFn,
    rasterize: PageIter,
) -> tuple[int, str | None]:
    """Run primary engine; LLM fallback on pages with confidence < threshold."""
    page_count = 0
    try:
        with pages_path.open("w") as fh:
            for page_idx, img in enumerate(rasterize(pdf_path, dpi), start=1):
                ptext, pconf = run_primary(img)
                llm_run: tuple[str, float] | None = None
                if ocr_auto.should_fallback(pconf):
                    log.info(
                        "ocr.auto.fallback",
                        page=page_idx,
                        primary_engine=primary_engine,
                        primary_conf=pconf,
                        threshold=settings.ocr_llm_threshold,
                    )
                    llm_run = ocr_llm.ocr_image(img)
                row = ocr_auto.build_auto_row(
                    page_idx, primary_engine, ptext, pconf, llm_run
                )
                fh.write(json.dumps(row) + "\n")
                page_count += 1
    except Exception as exc:
        return page_count, f"{type(exc).__name__}: {exc}"
    return page_count, None
