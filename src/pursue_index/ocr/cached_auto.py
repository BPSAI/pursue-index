"""Cache-aware auto-mode upgrade for an existing primary-engine pages.jsonl.

A ``pursue ocr run --engine auto --force`` (the retired auto mode)
re-rasterizes and re-OCRs every page. When the corpus already has a clean
primary-engine pass on disk (e.g. the 116-card Surya snapshot), we want a
cheaper path that leaves above-threshold pages untouched and only re-OCRs
the sub-threshold ones via the LLM fallback.

This module owns that upgrade. ``upgrade_pages_jsonl`` reads the
existing rows, renders only the low-confidence pages from the source
PDF, calls the LLM on those, and rewrites pages.jsonl in place with the
auto-mode row shape (LLM text wins, primary block preserved).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from pursue_index import get_logger
from pursue_index.ocr import auto as ocr_auto

log = get_logger(__name__)

RenderPageFn = Callable[[Path, int, int], Image.Image]
LLMOcrFn = Callable[[Image.Image], tuple[str, float]]


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _is_already_upgraded(row: dict) -> bool:
    """Row was previously promoted by auto-mode — has a ``primary`` block."""
    return "primary" in row


def _needs_upgrade(row: dict, threshold: float) -> bool:
    if _is_already_upgraded(row):
        return False
    return float(row.get("confidence", 0.0)) < threshold


def _build_upgraded_row(
    row: dict, primary_engine: str, llm_text: str, llm_conf: float
) -> dict:
    return ocr_auto.build_auto_row(
        page_idx=int(row["page"]),
        primary_engine=primary_engine,
        primary_text=row["text"],
        primary_conf=float(row["confidence"]),
        llm_run=(llm_text, llm_conf),
    )


def upgrade_pages_jsonl(
    pages_path: Path,
    pdf_path: Path,
    primary_engine: str,
    threshold: float,
    render_page: RenderPageFn,
    llm_ocr: LLMOcrFn,
    dpi: int,
) -> tuple[bool, int]:
    """Apply LLM fallback in-place to sub-threshold rows of ``pages_path``.

    ``render_page(pdf_path, page_idx_1based, dpi)`` returns a PIL image;
    ``llm_ocr(img)`` returns ``(text, confidence)``. Returns
    ``(rewrote, llm_calls)``: ``rewrote`` is True iff at least one page
    was upgraded.
    """
    rows = _read_rows(pages_path)
    upgrades = 0
    new_rows: list[dict] = []
    for row in rows:
        if not _needs_upgrade(row, threshold):
            new_rows.append(row)
            continue
        page_idx = int(row["page"])
        log.info(
            "ocr.cached_auto.fallback",
            page=page_idx,
            primary_conf=row.get("confidence"),
            threshold=threshold,
        )
        img = render_page(pdf_path, page_idx, dpi)
        llm_text, llm_conf = llm_ocr(img)
        new_rows.append(
            _build_upgraded_row(row, primary_engine, llm_text, llm_conf)
        )
        upgrades += 1

    if upgrades == 0:
        return False, 0
    _write_rows(pages_path, new_rows)
    return True, upgrades
