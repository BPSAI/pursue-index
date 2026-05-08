"""Auto-mode OCR: primary engine first, LLM re-OCR for low-confidence pages.

This module is deliberately thin — it composes the primary engine seam
(``ocr_image`` from ``pipeline`` or ``surya``) and the LLM seam
(``llm.ocr_image``) without owning the page-streaming loop. Pipeline holds
that loop; auto-mode just answers "given this page result, do we re-OCR
via LLM, and what does the row look like?"
"""

from __future__ import annotations

from typing import Any

from pursue_index import get_logger
from pursue_index.config import settings

log = get_logger(__name__)


def is_gpu_extra_installed() -> bool:
    """Return True if ``surya-ocr`` is importable. Cached at module level."""
    try:
        import surya  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_primary_engine(override: str | None = None) -> str:
    """Pick the auto-mode primary engine. ``override`` wins if provided.

    Falls back to ``surya`` when the GPU extra is installed, else ``tesseract``.
    """
    if override is not None:
        return override
    return "surya" if is_gpu_extra_installed() else "tesseract"


def llm_engine_name() -> str:
    """Engine label written into ``pages.jsonl`` for LLM-fallback rows."""
    return f"llm-{settings.ocr_llm_provider}"


def auto_meta_engine(primary: str) -> str:
    """``meta.json`` ``engine`` field for an auto-mode run."""
    return f"auto:{primary}+{llm_engine_name()}"


def build_auto_row(
    page_idx: int,
    primary_engine: str,
    primary_text: str,
    primary_conf: float,
    llm_run: tuple[str, float] | None,
) -> dict[str, Any]:
    """Compose a ``pages.jsonl`` row for one auto-mode page.

    When the LLM ran, the LLM result wins as the top-level ``text`` /
    ``confidence`` / ``engine``, and the primary attempt is preserved as a
    sibling ``primary`` block for transparency. When the LLM did not run,
    the row matches the single-engine shape.
    """
    if llm_run is None:
        return {
            "page": page_idx,
            "text": primary_text,
            "confidence": primary_conf,
            "engine": primary_engine,
        }

    llm_text, llm_conf = llm_run
    return {
        "page": page_idx,
        "text": llm_text,
        "confidence": llm_conf,
        "engine": llm_engine_name(),
        "primary": {
            "engine": primary_engine,
            "text": primary_text,
            "confidence": primary_conf,
        },
    }


def should_fallback(primary_conf: float) -> bool:
    """``True`` if the page should be re-OCR'd via the LLM fallback."""
    return primary_conf < settings.ocr_llm_threshold
