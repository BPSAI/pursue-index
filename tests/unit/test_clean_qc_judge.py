"""Tests for ``pursue_index.clean.qc.judge``.

Anthropic SDK is mocked. Tests exercise: structured-output parsing,
content-filter graceful degradation, malformed-response fallback,
and the build_row helper that shapes the QC sidecar entry.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pursue_index.clean.qc import judge


# --- parse_judge_response -----------------------------------------------


def _well_formed_judge_payload() -> dict:
    return {
        "checks": {
            "hallucinated_facts":     {"verdict": "pass", "evidence": "", "severity": "none"},
            "fabricated_redactions":  {"verdict": "pass", "evidence": "", "severity": "none"},
            "length_ratio":           {"verdict": "pass", "ratio": 1.02, "severity": "none"},
            "voice_match":            {"verdict": "pass", "evidence": "", "severity": "none"},
            "page_boundary_fidelity": {"verdict": "pass", "evidence": "", "severity": "none"},
            "ocr_artifact_handling":  {"verdict": "pass", "evidence": "", "severity": "none"},
            "verbatim_quotability":   {"verdict": "pass", "evidence": "", "severity": "none"},
            "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
        }
    }


def test_parse_judge_response_well_formed_json() -> None:
    raw = json.dumps(_well_formed_judge_payload())
    parsed = judge.parse_judge_response(raw)
    assert parsed is not None
    assert "checks" in parsed
    assert parsed["checks"]["hallucinated_facts"]["verdict"] == "pass"


def test_parse_judge_response_strips_code_fence() -> None:
    """Anthropic sometimes wraps JSON in ```json ... ``` despite the prompt."""
    raw = "```json\n" + json.dumps(_well_formed_judge_payload()) + "\n```"
    parsed = judge.parse_judge_response(raw)
    assert parsed is not None
    assert "checks" in parsed


def test_parse_judge_response_returns_none_for_malformed() -> None:
    assert judge.parse_judge_response("not json at all") is None
    assert judge.parse_judge_response("") is None


def test_parse_judge_response_returns_none_when_checks_missing() -> None:
    """A JSON payload lacking the `checks` block is unusable."""
    assert judge.parse_judge_response('{"some_other": "shape"}') is None


# --- build_row -----------------------------------------------------------


def test_build_row_produces_complete_sidecar_entry() -> None:
    """build_row composes the per-page QC entry with all provenance fields."""
    row = judge.build_row(
        card_id="abcd1234",
        page=7,
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
        checks=_well_formed_judge_payload()["checks"],
    )
    assert row["card_id"] == "abcd1234"
    assert row["page"] == 7
    assert row["raw_sha256"] == "raw_x"
    assert row["cleaned_sha256"] == "cleaned_x"
    assert row["judge_model_id"] == "claude-sonnet-4-6"
    assert row["judge_prompt_sha256"] == "prompt_x"
    assert "graded_at" in row
    assert "checks" in row
    assert row["aggregate"]["verdict"] == "pass"


def test_build_row_handles_judge_skipped_status() -> None:
    """When judge_skipped is set (e.g., content_filter), the row carries
    that reason and the checks block is set to all not_applicable."""
    row = judge.build_row(
        card_id="abcd1234",
        page=7,
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
        checks=None,
        judge_skipped="content_filter",
    )
    assert row["judge_skipped"] == "content_filter"
    assert row["aggregate"]["verdict"] == "not_applicable"
    for name, body in row["checks"].items():
        if name == "interpretive_cleanups":
            assert body["count"] == 0
        else:
            assert body["verdict"] == "not_applicable"


# --- grade_page integration (mocked client) -----------------------------


class _FakeUsage:
    def __init__(self, prompt: int, completion: int, cache_read: int = 0) -> None:
        self.input_tokens = prompt
        self.output_tokens = completion
        self.cache_read_input_tokens = cache_read
        self.cache_creation_input_tokens = 0


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _FakeMessage:
    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeContent(text)]
        self.usage = usage
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self._q = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        text, usage = self._q.pop(0)
        return _FakeMessage(text, usage)


class _FakeAnthropic:
    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self.messages = _FakeMessages(payloads)


def test_grade_page_returns_parsed_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(_well_formed_judge_payload())
    client = _FakeAnthropic([(payload, _FakeUsage(1200, 350))])
    monkeypatch.setattr(judge, "_get_client", lambda: client)
    result = judge.grade_page(
        raw_text="some raw text",
        cleaned_text="some cleaned text",
        model_id="claude-sonnet-4-6",
    )
    assert result.checks is not None
    assert result.usage["input_tokens"] == 1200
    assert result.usage["output_tokens"] == 350
    assert result.judge_skipped is None


def test_grade_page_handles_content_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror the cleaner's content-filter graceful-skip pattern."""
    def fail_with_content_filter(**kwargs: Any) -> Any:
        from anthropic import BadRequestError  # type: ignore
        from httpx import Request, Response
        req = Request("POST", "https://api.anthropic.com/v1/messages")
        resp = Response(400, request=req, json={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Output blocked by content filtering policy"
            },
            "request_id": "req_test123",
        })
        raise BadRequestError(message="content filtering policy", response=resp, body=resp.json())
    client = _FakeAnthropic([])
    client.messages.create = fail_with_content_filter  # type: ignore[method-assign]
    monkeypatch.setattr(judge, "_get_client", lambda: client)
    result = judge.grade_page(
        raw_text="potentially flagged content",
        cleaned_text="cleaned version",
        model_id="claude-sonnet-4-6",
    )
    assert result.judge_skipped == "content_filter"
    assert result.checks is None
