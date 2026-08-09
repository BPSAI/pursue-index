"""Anthropic vision client for the observation stage.

Mirrors the Anthropic client patterns in ``ocr.llm``: a cached client, a
system prompt sent with ``cache_control=ephemeral``, and the same 1568px
longest-edge cap the vision API wants. The model is pinned as a **code
constant** (``VISION_MODEL``), not read from ``.env`` — following the
judge-model precedent (``clean_qc_cli.DEFAULT_JUDGE_MODEL``): a corpus's
observation provenance must not silently change with an operator's environment.

This is the only module that spends. Tests inject a fake ``examine_fn`` into
``vision.run`` and never import the live client path; CI never runs it.
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

from PIL import Image

from pursue_index import get_logger

log = get_logger(__name__)

# Pinned vision model — matches the frozen July artifact's ``our_pass.model``
# and ``embed.image_observations.DEFAULT_MODEL``. Bump here, in code, on a
# deliberate model change; never via an environment variable.
VISION_MODEL = "claude-opus-4-8"

# Anthropic vision rejects images whose base64 exceeds ~5 MB; cap the longest
# edge as ``ocr.llm`` does.
_MAX_IMAGE_EDGE_PX = 1568

_SYSTEM_PROMPT = """You are a meticulous vision examiner for declassified U.S. \
government image releases (photographs, illustrations, composite figures, and \
image-only document pages that carry no machine-readable text).

Describe ONLY what is physically visible in THIS image. Do not speculate about \
provenance, do not infer content from outside knowledge, and do not identify \
real individuals. Transcribe any legible text verbatim; if none is legible, \
leave it empty.

Return STRICT JSON with exactly these fields:
{
  "image_type": "<short phrase, e.g. 'black-and-white photograph'>",
  "description": "<one faithful paragraph describing what is visible>",
  "visible_text": "<verbatim legible text, or empty string>",
  "observations": [
    {"claim": "<one concrete, checkable observation>",
     "kind": "observation",
     "confidence": "high|medium|low"}
  ]
}

Prefer concrete nouns a researcher would search for. Do not add commentary \
outside the JSON object."""

_client: Any = None


def _get_anthropic_client() -> Any:
    """Return a cached Anthropic client. Lazy-imports the SDK."""
    global _client
    if _client is not None:
        return _client
    import anthropic  # type: ignore[import-not-found]

    _client = anthropic.Anthropic()
    return _client


def _resize_for_vision(img: Image.Image) -> Image.Image:
    longest = max(img.width, img.height)
    if longest <= _MAX_IMAGE_EDGE_PX:
        return img
    scale = _MAX_IMAGE_EDGE_PX / longest
    new_size = (int(img.width * scale), int(img.height * scale))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _image_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    _resize_for_vision(rgb).save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _build_request(image_b64: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 2048,
        "system": [
            {"type": "text", "text": _SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png", "data": image_b64}},
                    {"type": "text",
                     "text": "Examine this image. Respond with only the JSON object."},
                ],
            }
        ],
    }


def _parse_response(raw: str) -> dict[str, Any]:
    """Parse the model's JSON reply into an examination dict.

    Tolerates a fenced code block; falls back to a bare-description dict so a
    non-JSON reply still yields a usable (if minimal) observation page.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"image_type": "", "description": raw.strip(),
                "visible_text": "", "observations": []}
    data.setdefault("observations", [])
    return data


def examine_image(img: Image.Image, *, model: str = VISION_MODEL) -> dict[str, Any]:
    """Return an examination dict for one image via Anthropic vision.

    The dict has ``image_type`` / ``description`` / ``visible_text`` /
    ``observations`` — the page shape ``sidecar.build_sidecar`` consumes. This
    performs a live API call; it is only reached from the ``--live-smoke`` path
    or an operator-attended bulk run.
    """
    client = _get_anthropic_client()
    request = _build_request(_image_to_b64(img), model)
    log.info("vision.call", model=model)
    response = client.messages.create(**request)
    usage = getattr(response, "usage", None)
    log.info(
        "vision.usage", model=model,
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
    )
    raw = response.content[0].text if response.content else ""
    return _parse_response(raw)
