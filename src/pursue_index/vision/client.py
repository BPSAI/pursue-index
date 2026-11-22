"""Anthropic vision client for the observation stage.

Mirrors the Anthropic client patterns in ``ocr.llm``: a cached client and the
same 1568px longest-edge cap the vision API wants. The model is pinned as a **code
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
from pursue_index.vision.sidecar import normalize_observations

log = get_logger(__name__)

# Pinned vision model — matches the frozen July artifact's ``our_pass.model``
# and ``embed.image_observations.DEFAULT_MODEL``. Bump here, in code, on a
# deliberate model change; never via an environment variable.
VISION_MODEL = "claude-opus-4-8"

# Anthropic vision rejects images whose base64 exceeds ~5 MB; cap the longest
# edge as ``ocr.llm`` does.
_MAX_IMAGE_EDGE_PX = 1568

# Why the system block carries no ``cache_control`` marker: prompt caching only
# applies to a prefix of at least 1,024 tokens on claude-opus-4-8 (512 on
# claude-opus-5-5). ``_SYSTEM_PROMPT`` is about 230 tokens, so a marker would
# silently do nothing (``cache_creation_input_tokens`` stays 0, no error), and
# padding the prompt up to the minimum would cost more than it could save. The
# prompt text is also left as is, because changing it would change the
# provenance of the observations already made with it. Do not re-add a marker
# unless the prefix really exceeds the minimum; the ``vision.usage`` log line
# reports the cache token counts so that can be checked.
_DEFAULT_MAX_TOKENS = 2048

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


class VisionClientError(RuntimeError):
    """The vision client cannot be built: no SDK or no key."""


def _get_anthropic_client() -> Any:
    """Return a cached Anthropic client. Lazy-imports the SDK."""
    global _client
    if _client is not None:
        return _client
    try:
        import anthropic
    except ImportError as exc:
        raise VisionClientError(
            "the anthropic SDK is not installed; no call was made"
        ) from exc

    from pursue_index.config.credentials import anthropic_api_key

    key = anthropic_api_key()
    if not key:
        raise VisionClientError("ANTHROPIC_API_KEY is not set; no call was made")
    _client = anthropic.Anthropic(api_key=key)
    return _client


def require_client() -> None:
    """Build the client now, so a missing SDK or key fails before anything is reserved.

    ``examine_image`` reuses the cached client, so the run builds it once.
    """
    _get_anthropic_client()


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


def _build_request(
    image_b64: str,
    model: str,
    *,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    effort: str | None = None,
) -> dict[str, Any]:
    """The request body. ``max_tokens`` and ``effort`` exist for models whose
    thinking tokens count against ``max_tokens`` (claude-opus-5-5); the pinned
    model's request is unchanged by leaving them at their defaults."""
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": _SYSTEM_PROMPT}],
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
    if effort is not None:
        request["output_config"] = {"effort": effort}
    return request


def _reply_text(response: Any) -> str:
    """The reply's text blocks, skipping thinking blocks that may lead it."""
    texts = [t for b in (response.content or [])
             if isinstance(t := getattr(b, "text", None), str)]
    return "".join(texts)


def _parse_response(raw: str) -> dict[str, Any]:
    """Parse the model's JSON reply into an examination dict.

    Tolerates a fenced code block; falls back to a bare-description dict so a
    non-JSON reply still yields a usable (if minimal) observation page. The
    ``observations`` list is normalized to the entries the sidecar schema
    defines, so a reply whose shape differs from the requested one becomes a
    valid page here rather than reaching the schema unchecked. A page that
    ends up describing nothing is left for the run to record as such.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"image_type": "", "description": raw.strip(),
                "visible_text": "", "observations": []}
    data: dict[str, Any] = dict(parsed) if isinstance(parsed, dict) else {}
    data.setdefault("description", raw.strip() if not data else "")
    data["observations"] = normalize_observations(data.get("observations"))
    return data


def _usage_dict(usage: Any) -> dict[str, int] | None:
    """The billed token counts, for the run's spend meter (not a sidecar field).

    None when the response carried no ``usage``: absent must stay absent so the
    meter charges the call its worst case instead of a zero-token price.
    """
    if usage is None:
        return None
    keys = ("input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens")
    return {k: int(getattr(usage, k, 0) or 0) for k in keys}


def examine_image(
    img: Image.Image,
    *,
    model: str = VISION_MODEL,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    effort: str | None = None,
) -> dict[str, Any]:
    """Return an examination dict for one image via Anthropic vision.

    The dict has ``image_type`` / ``description`` / ``visible_text`` /
    ``observations`` — the page shape ``sidecar.build_sidecar`` consumes. This
    performs a live API call; it is only reached from the ``--live-smoke`` path
    or an operator-attended bulk run. ``_usage`` and ``_stop_reason`` are
    metering/diagnostic records, not page data.
    """
    client = _get_anthropic_client()
    request = _build_request(_image_to_b64(img), model,
                             max_tokens=max_tokens, effort=effort)
    log.info("vision.call", model=model)
    response = client.messages.create(**request)
    usage = getattr(response, "usage", None)
    log.info(
        "vision.usage", model=model,
        input_tokens=getattr(usage, "input_tokens", 0),
        output_tokens=getattr(usage, "output_tokens", 0),
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
    result = _parse_response(_reply_text(response))
    counted = _usage_dict(usage)
    if counted is not None:
        result["_usage"] = counted
    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason is not None:
        result["_stop_reason"] = str(stop_reason)
    return result
