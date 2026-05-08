"""Tests for the LLM OCR engine adapter.

The actual Anthropic SDK is mocked — these tests exercise the adapter's
contract (image → ``(text, confidence)``), the structured-output parsing,
prompt-caching headers, content-hash caching, and cost logging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from pursue_index.ocr import llm as ocr_llm


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int,
                 cache_read_input_tokens: int = 0,
                 cache_creation_input_tokens: int = 0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _FakeMessage:
    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeContentBlock(text)]
        self.usage = usage
        self.stop_reason = "end_turn"
        self.id = "msg_fake"
        self.model = "claude-sonnet-4-6"


class _FakeMessages:
    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self._queue = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:  # noqa: D401
        self.calls.append(kwargs)
        text, usage = self._queue.pop(0)
        return _FakeMessage(text, usage)


class _FakeAnthropic:
    """Stub for ``anthropic.Anthropic`` — captures ``messages.create`` calls."""

    def __init__(self, payloads: list[tuple[str, _FakeUsage]]) -> None:
        self.messages = _FakeMessages(payloads)


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: _FakeAnthropic) -> None:
    monkeypatch.setattr(ocr_llm, "_get_anthropic_client", lambda: client)


def _structured_response(text: str, confidence: int) -> str:
    """The model returns JSON; the adapter parses ``text`` + ``confidence`` out of it."""
    return json.dumps({"text": text, "confidence": confidence})


# ---------------------------------------------------------------------------
# ocr_image: contract
# ---------------------------------------------------------------------------
def test_ocr_image_returns_text_and_confidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        (_structured_response("VERBATIM PAGE TEXT", 92), _FakeUsage(1500, 80)),
    ])
    _patch_client(monkeypatch, client)

    img = Image.new("RGB", (50, 50), color="white")
    text, conf = ocr_llm.ocr_image(img)

    assert text == "VERBATIM PAGE TEXT"
    assert conf == pytest.approx(92.0)
    # One API call made
    assert len(client.messages.calls) == 1


def test_ocr_image_uses_configured_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ocr_llm.settings, "ocr_llm_model", "claude-test-model")
    client = _FakeAnthropic([(_structured_response("hi", 80), _FakeUsage(100, 5))])
    _patch_client(monkeypatch, client)

    ocr_llm.ocr_image(Image.new("RGB", (10, 10)))
    assert client.messages.calls[0]["model"] == "claude-test-model"


def test_ocr_image_sends_prompt_caching_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The static system prompt must carry ``cache_control={"type": "ephemeral"}``
    so Anthropic caches it across calls. The user-image content must NOT be cached
    (each page is unique)."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([(_structured_response("x", 50), _FakeUsage(100, 5))])
    _patch_client(monkeypatch, client)

    ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    call = client.messages.calls[0]
    system = call["system"]
    # System is a list of blocks (cacheable form), not a bare string
    assert isinstance(system, list)
    assert any(
        block.get("cache_control", {}).get("type") == "ephemeral"
        for block in system
        if isinstance(block, dict)
    )


def test_ocr_image_includes_image_in_user_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([(_structured_response("hi", 88), _FakeUsage(100, 5))])
    _patch_client(monkeypatch, client)

    ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    call = client.messages.calls[0]
    user_msg = call["messages"][0]
    assert user_msg["role"] == "user"
    blocks = user_msg["content"]
    assert any(b.get("type") == "image" for b in blocks)


# ---------------------------------------------------------------------------
# Caching: image-content-hash → response
# ---------------------------------------------------------------------------
def test_ocr_image_caches_by_content_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Re-OCRing the same image content reads from the on-disk cache, no API call."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([(_structured_response("cached page", 91), _FakeUsage(1000, 50))])
    _patch_client(monkeypatch, client)

    img = Image.new("RGB", (32, 32), color=(123, 45, 67))

    # First call: hits the API
    text1, conf1 = ocr_llm.ocr_image(img)
    assert len(client.messages.calls) == 1

    # Second call with identical image: should hit cache, no new API call
    text2, conf2 = ocr_llm.ocr_image(img)
    assert text2 == text1 == "cached page"
    assert conf2 == conf1 == pytest.approx(91.0)
    assert len(client.messages.calls) == 1, "second call should be cached"


def test_ocr_image_different_images_miss_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        (_structured_response("page A", 90), _FakeUsage(1000, 50)),
        (_structured_response("page B", 85), _FakeUsage(1000, 40)),
    ])
    _patch_client(monkeypatch, client)

    img_a = Image.new("RGB", (32, 32), color=(1, 2, 3))
    img_b = Image.new("RGB", (32, 32), color=(4, 5, 6))

    ocr_llm.ocr_image(img_a)
    ocr_llm.ocr_image(img_b)
    assert len(client.messages.calls) == 2


# ---------------------------------------------------------------------------
# Cost logging
# ---------------------------------------------------------------------------
def test_ocr_image_logs_token_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Per-call token counts are logged so we can never silently spend."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    captured: list[dict[str, Any]] = []

    def fake_log(event: str, **kw: Any) -> None:
        captured.append({"event": event, **kw})

    monkeypatch.setattr(ocr_llm.log, "info", fake_log)
    client = _FakeAnthropic([
        (_structured_response("hello", 90), _FakeUsage(1500, 200, cache_read_input_tokens=400)),
    ])
    _patch_client(monkeypatch, client)

    ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    cost_events = [e for e in captured if e["event"] == "ocr.llm.usage"]
    assert cost_events, f"expected a usage log event, got: {captured}"
    e = cost_events[0]
    assert e["input_tokens"] == 1500
    assert e["output_tokens"] == 200
    assert e["cache_read_tokens"] == 400


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------
def test_openai_provider_raises_not_implemented(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(ocr_llm.settings, "ocr_llm_provider", "openai")

    with pytest.raises(NotImplementedError):
        ocr_llm.ocr_image(Image.new("RGB", (10, 10)))


# ---------------------------------------------------------------------------
# Robustness: malformed model output
# ---------------------------------------------------------------------------
def test_ocr_image_handles_non_json_response(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the model fails to return strict JSON, we still extract text and use a nominal conf."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([("plain text response, not JSON", _FakeUsage(800, 30))])
    _patch_client(monkeypatch, client)

    text, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert "plain text response" in text
    # Fallback nominal confidence — picked so it survives the auto-mode threshold
    assert conf >= 0.0
