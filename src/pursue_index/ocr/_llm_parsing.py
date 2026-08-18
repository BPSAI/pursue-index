"""Response-parsing helpers for ``pursue_index.ocr.llm``.

Extracted to keep ``llm.py`` under the per-file function-count cap. All
functions here are pure (no I/O, no SDK dependency); they consume the
raw text body returned by the Anthropic SDK and produce the normalized
``(text, confidence)`` plus usage shapes that the orchestration layer
needs.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Nominal confidence used when the model fails to return structured JSON.
# Set above the default ocr_llm_threshold (70) so a parse-failure response
# isn't recursively re-OCR'd by auto-mode.
NOMINAL_CONFIDENCE = 75.0

ZERO_USAGE: dict[str, int] = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_tokens": 0,
    "cache_creation_tokens": 0,
}

# Envelope-recovery regex pair. The model occasionally
# returns ``{"text": "...", "confidence": N}`` with unescaped inner
# double-quotes (typically from stamps or quoted names on the source
# page), which defeats both ``json.loads`` and ``raw_decode``. The
# envelope's wrapper is still well-formed, so regex-locate the open and
# close, extract the inner span, and manually expand the standard JSON
# escape sequences.
_ENVELOPE_OPEN_RE = re.compile(
    r'^\s*(?:```(?:json)?\s*)?\{[\s\n]*"text"\s*:\s*"',
    re.IGNORECASE,
)
_ENVELOPE_CLOSE_RE = re.compile(
    r'"\s*,\s*"confidence"\s*:\s*(\d+(?:\.\d+)?)\s*\}\s*(?:```\s*)?$',
    re.IGNORECASE,
)


def extract_usage(response_usage: Any) -> dict[str, int]:
    """Normalize an Anthropic SDK ``usage`` object to a plain dict."""
    return {
        "input_tokens": getattr(response_usage, "input_tokens", 0),
        "output_tokens": getattr(response_usage, "output_tokens", 0),
        "cache_read_tokens": getattr(response_usage, "cache_read_input_tokens", 0),
        "cache_creation_tokens": getattr(response_usage, "cache_creation_input_tokens", 0),
    }


def find_text_json_object(raw: str) -> dict[str, Any] | None:
    """Scan ``raw`` for the first JSON object that decodes AND has a "text"
    key. Returns the parsed dict, or ``None`` if no such block exists.

    Necessary because real model output sometimes wraps the JSON envelope in
    chatter that itself contains stray ``{`` / ``}`` (transcribed prose,
    handwritten margin marks, math). A naive ``\\{.*\\}`` greedy DOTALL match
    spans from the first prose-brace to the last brace and fails to parse.

    Strategy: walk every ``{`` position; for each, try ``json.JSONDecoder``'s
    ``raw_decode`` to locate a balanced object. Return the first that decodes
    AND contains ``"text"`` — that's the schema we asked the model for.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "text" in obj:
            return obj
    return None


def recover_envelope(raw: str) -> tuple[str, float] | None:
    """Recover ``(text, confidence)`` from a malformed-but-shaped envelope.

    Returns ``None`` if ``raw`` doesn't match the canonical wrapper, in
    which case the caller falls through to the raw-text default.
    """
    open_match = _ENVELOPE_OPEN_RE.match(raw)
    close_match = _ENVELOPE_CLOSE_RE.search(raw)
    if not (open_match and close_match):
        return None
    inner = raw[open_match.end():close_match.start()]
    inner = (
        inner.replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace("\\r", "\r")
             .replace('\\"', '"')
             .replace("\\\\", "\\")
    )
    try:
        confidence = float(close_match.group(1))
    except (TypeError, ValueError):
        confidence = NOMINAL_CONFIDENCE
    return inner, confidence


def parse_response(raw: str) -> tuple[str, float]:
    """Pull ``text`` + ``confidence`` from the model's reply.

    Tries strict JSON first, then scans for the first balanced JSON object
    that has a ``"text"`` field, then attempts envelope-pattern recovery
    for the unescaped-inner-quote artifact; falls back to using the whole
    reply as text with a nominal confidence so a malformed response never
    breaks the page.
    """
    raw = raw.strip()
    obj: dict[str, Any] | None = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            obj = parsed
    except json.JSONDecodeError:
        obj = find_text_json_object(raw)

    if obj is None:
        recovered = recover_envelope(raw)
        if recovered is not None:
            return recovered
        return raw, NOMINAL_CONFIDENCE

    text = str(obj.get("text", ""))
    conf_raw = obj.get("confidence", NOMINAL_CONFIDENCE)
    try:
        confidence = float(conf_raw)
    except (TypeError, ValueError):
        confidence = NOMINAL_CONFIDENCE
    return text, confidence
