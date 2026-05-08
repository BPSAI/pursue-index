"""LLM-based OCR fallback (Anthropic vision).

This module provides an ``ocr_image(img) -> (text, confidence)`` seam matching
the contract used by ``ocr.pipeline.ocr_image`` (Tesseract) and
``ocr.surya.ocr_image`` (Surya), so it slots directly into ``_run_engine``
without changing orchestration.

The default provider is Anthropic; OpenAI is a stub for v1. The system prompt
is sent with ``cache_control={"type": "ephemeral"}`` so subsequent calls in
the same window pay the cache-read rate (~10× cheaper) for the static
instructions. Per-page responses are also cached on disk by image
content-hash, so re-runs of the same PDF spend zero tokens.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from pursue_index import get_logger
from pursue_index.config import settings

log = get_logger(__name__)

_client: Any = None

# Nominal confidence used when the model fails to return structured JSON.
# Set above the default ocr_llm_threshold (70) so a parse-failure response
# isn't recursively re-OCR'd by auto-mode.
_NOMINAL_CONFIDENCE = 75.0

# Anthropic vision API rejects images > 5 MB base64-encoded. Cap the longest
# edge so high-DPI rasters get downscaled before the encode step.
_MAX_IMAGE_EDGE_PX = 1568

_SYSTEM_PROMPT = """You are an expert OCR engine for declassified U.S. government documents \
(typewriter scans, faded carbon copies, multi-column FBI forms, hand-stamped redactions, \
marginalia, and handwritten annotations).

Transcribe every page VERBATIM:
- Preserve original line breaks, spacing, and capitalization.
- Mark any redacted region (black bar, white-out, or "REDACTED" stamp) as [REDACTED].
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


def _parse_response(raw: str) -> tuple[str, float]:
    """Pull ``text`` + ``confidence`` from the model's reply.

    Tries strict JSON first, then a relaxed JSON-block regex; falls back to
    using the whole reply as text with a nominal confidence so a malformed
    model response never breaks the page.
    """
    raw = raw.strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match is None:
            return raw, _NOMINAL_CONFIDENCE
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return raw, _NOMINAL_CONFIDENCE

    text = str(obj.get("text", "")) if isinstance(obj, dict) else str(obj)
    conf_raw = obj.get("confidence", _NOMINAL_CONFIDENCE) if isinstance(obj, dict) else _NOMINAL_CONFIDENCE
    try:
        confidence = float(conf_raw)
    except (TypeError, ValueError):
        confidence = _NOMINAL_CONFIDENCE
    return text, confidence


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


def _ocr_image_anthropic(img: Image.Image, sha: str) -> tuple[str, float]:
    """Call Anthropic vision for a single page image; return ``(text, conf)``."""
    client = _get_anthropic_client()
    request = _build_request(_image_to_b64(img))
    log.info("ocr.llm.call", provider="anthropic", model=settings.ocr_llm_model, sha=sha[:12])
    response = client.messages.create(**request)
    _log_usage(response.usage)
    raw = response.content[0].text if response.content else ""
    return _parse_response(raw)


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return ``(text, confidence)`` for a single page image via the LLM.

    Looks up a content-hash cache first; falls back to the configured provider
    (Anthropic by default). OpenAI is a stub for v1.
    """
    sha = _image_hash(img)
    cached = _load_cached(sha)
    if cached is not None:
        log.info("ocr.llm.cache_hit", sha=sha[:12])
        return cached

    provider = settings.ocr_llm_provider
    if provider == "anthropic":
        text, confidence = _ocr_image_anthropic(img, sha)
    elif provider == "openai":
        raise NotImplementedError(
            "OpenAI provider is a v2 stub; set PURSUE_OCR_LLM_PROVIDER=anthropic for now."
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    _store_cached(sha, text, confidence)
    return text, confidence
