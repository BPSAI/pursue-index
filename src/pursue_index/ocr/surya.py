"""Surya OCR engine adapter.

Surya is a transformer-based OCR model that runs on GPU. This module exposes
an ``ocr_image(img) -> (text, confidence)`` seam matching the contract used by
``ocr.pipeline.ocr_image`` (the Tesseract path), so it slots directly into
``_run_engine`` without changing orchestration.

The recognition predictor is loaded lazily on first use and cached as a module
singleton — model load is expensive (~few seconds), per-call inference is
cheap. ``surya-ocr`` is an optional dep (``pursue-index[gpu]``); the import
is deferred to first call so the module can be imported on CPU-only hosts
without crashing at startup.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from pursue_index import get_logger

log = get_logger(__name__)

_predictor: Any = None


def _get_predictor() -> Any:
    """Return the cached Surya recognition predictor, loading on first call.

    Imports surya lazily so that environments without the GPU extras can
    still import this module (patched in tests, never invoked at runtime).
    """
    global _predictor
    if _predictor is not None:
        return _predictor

    from surya.foundation import FoundationPredictor
    from surya.recognition import RecognitionPredictor

    log.info("ocr.surya.load_model")
    foundation = FoundationPredictor()
    _predictor = RecognitionPredictor(foundation)
    log.info("ocr.surya.load_model.done")
    return _predictor


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return ``(text, mean_line_confidence)`` for a single page image.

    Matches the shape of ``ocr.pipeline.ocr_image`` (the Tesseract path).
    Surya emits per-line confidences in [0, 1]; we scale to [0, 100] so the
    confidence column in ``pages.jsonl`` is comparable across engines.
    """
    predictor = _get_predictor()
    results = predictor([img])
    if not results:
        return "", 0.0

    page = results[0]
    lines = page.text_lines
    if not lines:
        return "", 0.0

    text = "\n".join(line.text for line in lines)
    confidences = [line.confidence for line in lines if line.confidence is not None]
    mean_conf_0_1 = sum(confidences) / len(confidences) if confidences else 0.0
    return text, mean_conf_0_1 * 100.0
