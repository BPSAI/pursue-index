"""Anthropic vision-text judge call for the clean-quality LLM-judge layer.

Mirrors the cleaner's content-filter graceful-skip pattern. Parses
structured-output JSON returned by the judge; tolerates code-fence
wrapping and a few common malformed-response shapes by returning
``None`` rather than crashing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pursue_index import get_logger
from pursue_index.clean.qc import schema
from pursue_index.clean.qc.prompt import build_user_message, judge_system_prompt

log = get_logger(__name__)

_client: Any = None


@dataclass
class GradeResult:
    """Outcome of one judge call. ``checks`` is None when the judge
    skipped (content filter, parse failure, etc.); ``judge_skipped``
    carries the reason."""
    checks: dict[str, Any] | None
    usage: dict[str, int]
    judge_skipped: str | None
    request_id: str | None = None


def _get_client() -> Any:
    """Return a cached Anthropic client. Monkeypatched in tests."""
    global _client
    if _client is not None:
        return _client
    import anthropic  # type: ignore[import-not-found]
    _client = anthropic.Anthropic()
    return _client


_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_judge_response(raw: str) -> dict | None:
    """Parse the judge's response into a dict with a `checks` key.

    Strips optional ```json ... ``` code fences. Returns None when the
    payload isn't well-formed JSON, isn't an object, or lacks `checks`.
    """
    if not raw or not raw.strip():
        return None
    body = raw.strip()
    m = _CODE_FENCE_RE.match(body)
    if m:
        body = m.group(1)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "checks" not in parsed:
        return None
    return parsed


def _all_not_applicable_checks() -> dict[str, dict[str, Any]]:
    """Build a fully-not_applicable checks block for skipped judge rows."""
    out: dict[str, dict[str, Any]] = {}
    for name in schema.CHECK_NAMES:
        if name == "interpretive_cleanups":
            out[name] = {"count": 0, "examples": [], "severity": "none"}
        elif name == "length_ratio":
            out[name] = {"verdict": "not_applicable", "ratio": 0.0, "severity": "none"}
        else:
            out[name] = {"verdict": "not_applicable", "evidence": "", "severity": "none"}
    return out


def build_row(
    *,
    card_id: str,
    page: int,
    raw_sha256: str,
    cleaned_sha256: str,
    judge_model_id: str,
    judge_prompt_sha256: str,
    checks: dict[str, dict[str, Any]] | None,
    judge_skipped: str | None = None,
) -> dict:
    """Compose the per-page QC sidecar entry, including the aggregate
    roll-up and provenance fields."""
    final_checks = checks if checks is not None else _all_not_applicable_checks()
    row: dict[str, Any] = {
        "card_id": card_id,
        "page": page,
        "raw_sha256": raw_sha256,
        "cleaned_sha256": cleaned_sha256,
        "judge_model_id": judge_model_id,
        "judge_prompt_sha256": judge_prompt_sha256,
        "graded_at": datetime.now(UTC).isoformat(),
        "checks": final_checks,
        "aggregate": schema.aggregate_checks(final_checks),
    }
    if judge_skipped is not None:
        row["judge_skipped"] = judge_skipped
    return row


def _classify_bad_request(exc: Exception) -> str | None:
    """Return ``content_filter`` if exc looks like Anthropic's content
    filter declining the response; None otherwise."""
    msg = str(exc).lower()
    if "content filtering" in msg or "content_filter" in msg:
        return "content_filter"
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", {})
        if isinstance(err, dict):
            t = err.get("type", "")
            if t in ("content_filter", "content_filtered"):
                return "content_filter"
    return None


def _extract_usage(usage: Any) -> dict[str, int]:
    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", 0),
    }


_ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0,
               "cache_read_tokens": 0, "cache_creation_tokens": 0}


def grade_page(*, raw_text: str, cleaned_text: str, model_id: str) -> GradeResult:
    """Call the judge for one page; return parsed checks + usage.

    Content-filter rejections come back as ``judge_skipped='content_filter'``
    with all-not_applicable verdicts. Parse failures land as
    ``judge_skipped='parse_failure'``.
    """
    client = _get_client()
    request = {
        "model": model_id,
        "max_tokens": 2048,
        "system": [{
            "type": "text",
            "text": judge_system_prompt(),
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{
            "role": "user",
            "content": build_user_message(raw_text, cleaned_text),
        }],
    }
    try:
        response = client.messages.create(**request)
    except Exception as exc:
        reason = _classify_bad_request(exc)
        if reason is not None:
            request_id = getattr(exc, "request_id", None)
            return GradeResult(
                checks=None, usage=dict(_ZERO_USAGE),
                judge_skipped=reason, request_id=request_id,
            )
        raise
    raw = response.content[0].text if response.content else ""
    usage = _extract_usage(response.usage)
    parsed = parse_judge_response(raw)
    if parsed is None or not isinstance(parsed.get("checks"), dict):
        return GradeResult(checks=None, usage=usage, judge_skipped="parse_failure")
    return GradeResult(checks=parsed["checks"], usage=usage, judge_skipped=None)
