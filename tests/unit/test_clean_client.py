"""Tests for the Anthropic client wrapper used by the cleanup stage.

The real SDK is mocked. We test contract, request shape, prompt-cache
header, and cost accounting.
"""

from __future__ import annotations

from typing import Any

import pytest

from pursue_index.clean import client as clean_client


class _FakeUsage:
    def __init__(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _FakeMessage:
    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = usage


class _FakeMessages:
    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self._queue = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        text, usage = self._queue.pop(0)
        return _FakeMessage(text, usage)


class _FakeAnthropic:
    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self.messages = _FakeMessages(payloads)


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _FakeAnthropic) -> None:
    monkeypatch.setattr(clean_client, "_get_client", lambda: fake)


def test_clean_page_returns_text_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clean_page → (cleaned_text, Usage) with cleaned text from the model."""
    fake = _FakeAnthropic([("cleaned page text", _FakeUsage(120, 110))])
    _patch(monkeypatch, fake)
    cleaned, usage = clean_client.clean_page(
        raw_text="raw page", model_id="claude-haiku-4-5-20251001"
    )
    assert cleaned == "cleaned page text"
    assert usage.input_tokens == 120
    assert usage.output_tokens == 110


def test_clean_page_request_has_cache_control_on_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System block must carry cache_control=ephemeral. That's the ~85%
    cache-read savings the cost model assumes."""
    fake = _FakeAnthropic([("ok", _FakeUsage(1, 1))])
    _patch(monkeypatch, fake)
    clean_client.clean_page(raw_text="abc", model_id="claude-haiku-4-5-20251001")
    req = fake.messages.calls[0]
    assert req["model"] == "claude-haiku-4-5-20251001"
    assert isinstance(req["system"], list)
    sys_block = req["system"][0]
    assert sys_block["type"] == "text"
    assert sys_block["cache_control"] == {"type": "ephemeral"}


def test_clean_page_passes_raw_text_as_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The raw OCR page text goes into the single user message verbatim.

    No reformatting at this seam — the system prompt is what tells the model
    what to do; we just hand it the input.
    """
    fake = _FakeAnthropic([("ok", _FakeUsage(1, 1))])
    _patch(monkeypatch, fake)
    clean_client.clean_page(
        raw_text="raw\npage\nbody", model_id="claude-haiku-4-5-20251001"
    )
    req = fake.messages.calls[0]
    user_msg = req["messages"][0]
    assert user_msg["role"] == "user"
    # Tolerate either string or content-block form so the wrapper can switch
    # later; just assert the raw text appears.
    content = user_msg["content"]
    if isinstance(content, str):
        assert "raw\npage\nbody" in content
    else:
        joined = " ".join(b.get("text", "") for b in content)
        assert "raw\npage\nbody" in joined


def test_estimate_cost_uses_haiku_4_5_rates() -> None:
    """Haiku-4-5 pricing per the plan: $0.80/M in, $4/M out (post-cache).

    estimate_cost_usd is what the runner uses to gate the budget cap.
    Treat cache-read tokens as the cheap rate (1/10th input).
    """
    cost = clean_client.estimate_cost_usd(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    assert cost == pytest.approx(0.80, rel=1e-3)
    cost_out = clean_client.estimate_cost_usd(
        input_tokens=0,
        output_tokens=1_000_000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    assert cost_out == pytest.approx(4.00, rel=1e-3)


def test_estimate_cost_cache_read_is_cheaper_than_uncached_input() -> None:
    """Cache-read tokens are 1/10th the regular input rate ($0.08/M)."""
    cached = clean_client.estimate_cost_usd(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=1_000_000,
        cache_creation_tokens=0,
    )
    assert cached == pytest.approx(0.08, rel=1e-3)
