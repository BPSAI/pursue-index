"""LLM-based OCR fallback (Anthropic vision).

This module provides an ``ocr_image(img) -> (text, confidence)`` seam matching
the contract used by ``ocr.pipeline.ocr_image`` (Tesseract) and
``ocr.surya.ocr_image`` (Surya), so it slots directly into ``_run_engine``
without changing orchestration.

The default provider is Anthropic; OpenAI is a stub for v1. The system prompt
is sent with ``cache_control={"type": "ephemeral"}`` so subsequent calls in
the same window pay the cache-read rate (~10x cheaper) for the static
instructions. Per-page responses are also cached on disk by image
content-hash, so re-runs of the same PDF spend zero tokens.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.ocr._llm_parsing import (
    ZERO_USAGE,
    extract_usage,
    parse_response,
)

log = get_logger(__name__)

_client: Any = None


class ContentFilterError(Exception):
    """Anthropic's output content filter blocked the page (HTTP 400).

    Distinct from other API errors so callers (the llm→dots fallback runner)
    can route just this case to the local backstop instead of failing the card.
    """


def _is_content_filter_error(exc: Exception) -> bool:
    """True if ``exc`` is Anthropic's output-content-filter 400.

    Message-based (no anthropic import needed): the SDK raises
    ``BadRequestError: ... 'Output blocked by content filtering policy'``.
    """
    msg = str(exc).lower()
    return "content filtering" in msg or "output blocked" in msg

# Anthropic vision API rejects images > 5 MB base64-encoded. Cap the longest
# edge so high-DPI rasters get downscaled before the encode step.
_MAX_IMAGE_EDGE_PX = 1568

_SYSTEM_PROMPT = """You are an expert OCR engine for declassified U.S. government documents \
(typewriter scans, faded carbon copies, multi-column FBI forms, hand-stamped redactions, \
marginalia, and handwritten annotations).

Transcribe every page VERBATIM:
- Preserve original line breaks, spacing, and capitalization.
- Mark a BLANK redacted region (black bar, white-out, or "REDACTED" stamp with no visible \
text) as [REDACTED]. If a redaction instead prints a FOIA exemption code in place of the \
withheld text (e.g. (b)(1), (b)(3), (b)(6), 1.4a), transcribe that code VERBATIM where it \
appears — the printed code is the redaction marker; do not add a [REDACTED] wrapper around it.
- A colored strike-through or line drawn over a still-legible classification marking \
(e.g. (SECRET//REL TO USA, FVEY), (S//RELIDO)) is a DECLASSIFICATION annotation, NOT a \
redaction. Transcribe the marking verbatim as content; do not mark it [REDACTED].
- Transcribe only what is physically visible on THIS page. If text is covered (e.g. by a \
label or sticker) or otherwise unreadable, mark it [ILLEGIBLE]. Do NOT fill it in from memory, \
from repeated boilerplate, or from outside knowledge — even if you "know" what a standard marking says.
- Mark any portion you cannot read with reasonable certainty as [ILLEGIBLE].
- Do not summarize, paraphrase, translate, or correct apparent typos.
- Do not add commentary.

Return your response as STRICT JSON with exactly two fields:
{
  "text": "<the verbatim transcription>",
  "confidence": <integer 0-100, your self-rated confidence in the transcription>
}

The "confidence" should reflect how legible the page is and how complete your transcription \
is. A clean typewritten page → 95+. A faded carbon with some illegible patches → 60-75. \
A nearly-blank or noise-only page → 0-20."""


def _get_anthropic_client() -> Any:
    """Return a cached Anthropic client. Lazy-imports the SDK."""
    global _client
    if _client is not None:
        return _client
    import anthropic  # type: ignore[import-not-found]

    _client = anthropic.Anthropic()
    return _client


def _cache_dir() -> Path:
    """Where image-hash → response JSON files live."""
    return settings.ocr_dir / ".llm-cache"


def _image_hash(img: Image.Image) -> str:
    """Stable content hash for an image (RGB pixel bytes + size)."""
    buf = io.BytesIO()
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    rgb.save(buf, format="PNG", optimize=False, compress_level=0)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def _prompt_version() -> str:
    """Short hash of the active system prompt.

    Folded into the cache key so a prompt-contract change busts the
    image-content cache — otherwise re-OCR would silently return the
    transcription produced under the OLD prompt.
    """
    return hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:8]


def _cache_key(img: Image.Image) -> str:
    """Cache key = image content hash + prompt version (prompt-aware)."""
    return f"{_image_hash(img)}-p{_prompt_version()}"


def _resize_for_vision(img: Image.Image) -> Image.Image:
    """Cap the longest edge at ``_MAX_IMAGE_EDGE_PX`` for the Anthropic API.

    300 DPI rasters of letter-sized pages routinely exceed the 5 MB base64
    limit; Anthropic's docs recommend ~1568px on the longest edge anyway.
    """
    longest = max(img.width, img.height)
    if longest <= _MAX_IMAGE_EDGE_PX:
        return img
    scale = _MAX_IMAGE_EDGE_PX / longest
    new_size = (int(img.width * scale), int(img.height * scale))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _image_to_b64(img: Image.Image) -> str:
    """Encode an image as base64 PNG for the Anthropic vision API."""
    buf = io.BytesIO()
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    resized = _resize_for_vision(rgb)
    resized.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _load_cached(sha: str) -> tuple[str, float] | None:
    cache_path = _cache_dir() / f"{sha}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload["text"], float(payload["confidence"])


def _store_cached(sha: str, text: str, confidence: float) -> None:
    cdir = _cache_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{sha}.json").write_text(
        json.dumps({"text": text, "confidence": confidence})
    )


def _build_request(image_b64: str) -> dict[str, Any]:
    """Anthropic ``messages.create`` kwargs for a single-page transcription.

    The system block is split out and marked ``cache_control=ephemeral`` so the
    static instruction text is billed at the cache-read rate after the first
    call in the window.
    """
    return {
        "model": settings.ocr_llm_model,
        "max_tokens": 8192,
        "system": [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Transcribe this page. Respond with only the JSON object.",
                    },
                ],
            }
        ],
    }


def _log_usage(usage: Any) -> None:
    """Emit a structured ``ocr.llm.usage`` event so we never silently spend."""
    log.info(
        "ocr.llm.usage",
        provider=settings.ocr_llm_provider,
        model=settings.ocr_llm_model,
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
    )


def _ocr_image_anthropic(
    img: Image.Image, sha: str
) -> tuple[str, float, dict[str, int]]:
    """Call Anthropic vision for a single page image.

    Returns ``(text, confidence, usage_dict)``. The usage dict has the
    same keys as ``ZERO_USAGE`` so the caller (tracker, cost cap) sees
    a stable shape regardless of which SDK fields were populated.
    """
    client = _get_anthropic_client()
    request = _build_request(_image_to_b64(img))
    log.info("ocr.llm.call", provider="anthropic", model=settings.ocr_llm_model, sha=sha[:12])
    try:
        response = client.messages.create(**request)
    except Exception as exc:
        if _is_content_filter_error(exc):
            log.warning("ocr.llm.content_filter", model=settings.ocr_llm_model, sha=sha[:12])
            raise ContentFilterError(str(exc)) from exc
        raise
    _log_usage(response.usage)
    raw = response.content[0].text if response.content else ""
    text, confidence = parse_response(raw)
    return text, confidence, extract_usage(response.usage)


def ocr_image_with_usage(
    img: Image.Image,
) -> tuple[str, float, dict[str, int]]:
    """Return ``(text, confidence, usage)`` for a single page image.

    ``usage`` is a dict with ``input_tokens`` / ``output_tokens`` /
    ``cache_read_tokens`` / ``cache_creation_tokens``. Cache hits return
    an all-zeros usage dict (no tokens spent), so a downstream tracker
    can sum without double-counting.

    Use this variant from cost-capped runs (``scripts/reocr_altered.py``).
    Use ``ocr_image`` if you only need the text + confidence.
    """
    sha = _cache_key(img)
    cached = _load_cached(sha)
    if cached is not None:
        log.info("ocr.llm.cache_hit", sha=sha[:12])
        return cached[0], cached[1], dict(ZERO_USAGE)

    provider = settings.ocr_llm_provider
    if provider == "anthropic":
        text, confidence, usage = _ocr_image_anthropic(img, sha)
    elif provider == "openai":
        raise NotImplementedError(
            "OpenAI provider is a v2 stub; set PURSUE_OCR_LLM_PROVIDER=anthropic for now."
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    _store_cached(sha, text, confidence)
    return text, confidence, usage


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return ``(text, confidence)`` for a single page image via the LLM.

    Looks up a content-hash cache first; falls back to the configured
    provider (Anthropic by default). Delegates to ``ocr_image_with_usage``
    and drops the usage dict — call that variant directly if you need
    token tracking.
    """
    text, confidence, _ = ocr_image_with_usage(img)
    return text, confidence
