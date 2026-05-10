"""Anthropic client wrapper for the cleanup stage.

Thin layer over ``messages.create`` that sends the cleanup system prompt
with ``cache_control=ephemeral`` so repeated per-page calls in the same
5-minute window pay the cache-read rate (~85% cheaper input tokens).

Distinct from ``ocr/llm.py`` because the cleanup pass is text-in / text-out
(no vision), has a different prompt (text correction, not transcription),
and a different cost ceiling (pilot-only until operator authorizes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pursue_index import get_logger
from pursue_index.clean.prompt import system_prompt

log = get_logger(__name__)

_client: Any = None

# Haiku-4-5 pricing per the plan: $0.80/M in, $4/M out, $0.08/M cache-read
# (cache-read is 1/10th input). Cache-creation (ephemeral) is billed at
# 1.25x the input rate (nayru P2 #4 — was previously coded as 1.0x,
# under-billing the first call in each cache window by ~25%).
_RATE_INPUT_PER_M = 0.80
_RATE_OUTPUT_PER_M = 4.00
_RATE_CACHE_READ_PER_M = 0.08
_RATE_CACHE_CREATION_PER_M = 1.25 * _RATE_INPUT_PER_M

# Conservative output cap: typical OCR page is ~600 tokens; budget headroom
# for the few long pages so we don't truncate mid-sentence.
_MAX_TOKENS = 4096


@dataclass(frozen=True)
class Usage:
    """Per-call token-usage tally for cost accounting."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _get_client() -> Any:
    """Lazy-import and cache the Anthropic SDK client."""
    global _client
    if _client is not None:
        return _client
    import anthropic  # type: ignore[import-not-found]

    _client = anthropic.Anthropic()
    return _client


def _build_request(raw_text: str, model_id: str) -> dict[str, Any]:
    """Build the ``messages.create`` kwargs with cache_control on system.

    User content is wrapped in ``<ocr_document>`` tags (laverna SEC-003)
    so OCR text that reads like instructions ("Disregard prior
    directives...") is structurally fenced off from the assistant's
    instructions. The system prompt acknowledges the tags so the model
    treats their contents as document text, not as a directive.
    """
    user_content = f"<ocr_document>\n{raw_text}\n</ocr_document>"
    return {
        "model": model_id,
        "max_tokens": _MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": user_content}],
            }
        ],
    }


def _extract_text(content: Any) -> str:
    """Concatenate all text blocks from a ``messages.create`` response.

    Codex P2: ``response.content`` is a list and can carry multiple
    ``TextBlock`` entries (e.g. when the model splits its reply, or
    after a thinking block). Reading only ``content[0].text`` silently
    drops everything after the first block — that truncates long
    cleanup outputs. We iterate, filter to text-typed blocks, and join
    with the empty string because Anthropic returns one continuous
    document split for streaming reasons, not as paragraph-separated
    sub-replies; a newline join would inject spurious blank lines into
    the cleaned transcript.

    Non-text blocks (``thinking``, tool-use, etc.) are skipped. The
    filter check runs BEFORE ``.text`` access so blocks that lack the
    attribute don't blow up.
    """
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "".join(parts)


def _extract_usage(usage: Any) -> Usage:
    """Coerce an SDK ``Usage`` object to our local dataclass."""
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
    )


def clean_page(raw_text: str, model_id: str) -> tuple[str, Usage]:
    """Send one page through the cleanup prompt; return (cleaned_text, usage).

    The raw text is sent verbatim — the system prompt tells the model what
    to fix. Output is the model's reply text, stripped of leading/trailing
    whitespace.
    """
    client = _get_client()
    request = _build_request(raw_text, model_id)
    log.info("clean.llm.call", model=model_id, input_chars=len(raw_text))
    response = client.messages.create(**request)
    usage = _extract_usage(response.usage)
    cleaned = _extract_text(response.content)
    log.info(
        "clean.llm.usage",
        model=model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read=usage.cache_read_tokens,
        cache_creation=usage.cache_creation_tokens,
    )
    return cleaned.strip(), usage


def estimate_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    """Convert a per-call token-usage tally to a USD cost estimate.

    Cache-read tokens are billed at the discounted rate; cache-creation
    tokens at the regular input rate. Callers should sum the per-call
    estimates and bail when the running total exceeds the budget cap.
    """
    in_cost = (input_tokens / 1_000_000) * _RATE_INPUT_PER_M
    out_cost = (output_tokens / 1_000_000) * _RATE_OUTPUT_PER_M
    cache_read_cost = (cache_read_tokens / 1_000_000) * _RATE_CACHE_READ_PER_M
    cache_create_cost = (
        cache_creation_tokens / 1_000_000
    ) * _RATE_CACHE_CREATION_PER_M
    return in_cost + out_cost + cache_read_cost + cache_create_cost
