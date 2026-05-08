"""OCR pipeline: PDF → per-page text + layout JSON.

Engine selection (``settings.ocr_engine``):
  * ``tesseract`` — local, free, fast on the 5090. Weak on faded scans, handwriting,
    and complex layouts.
  * ``azure``     — Azure Document Intelligence Layout model. Strong on historical
    scanned docs but costs ~$1.50/1k pages.
  * ``auto``      — try Tesseract; if confidence is low, retry with Azure DI.

Output convention, per PDF::

    settings.ocr_dir / {card_id} /
        pages.jsonl       # one JSON per page: {page, text, confidence, engine}
        layout.json       # full layout when available (Azure)
        meta.json         # source PDF size/hash, engine used, run timestamps
"""

from __future__ import annotations

from pursue_index import get_logger
from pursue_index.scrape.types import Manifest

log = get_logger(__name__)


async def ocr_all(manifest: Manifest) -> None:
    """OCR every PDF in the manifest that hasn't been processed."""
    # TODO(phase-3):
    #   - rasterize PDF with pdf2image at settings.ocr_dpi
    #   - run pytesseract per page, capture mean conf
    #   - if engine=auto and conf < threshold, fall back to Azure DI
    #   - write pages.jsonl + meta.json into ocr_dir/{card_id}/
    log.warning("ocr.not_implemented", card_count=manifest.card_count)
    raise NotImplementedError("OCR pipeline arrives in phase 3 — see docs/architecture.md")
