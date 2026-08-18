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


def test_ocr_image_parses_json_when_transcription_contains_braces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real OCR'd pages sometimes legitimately contain `{` characters in
    typewritten text (handwritten margin notes, math, weird stamps). The
    relaxed JSON-block regex was greedy and DOTALL — it would mis-parse
    a model that emits prose containing a stray `{` followed by a real
    JSON envelope. Tighten the parse to find the JSON object that has
    a "text" key, not just any matching `{...}` blob.
    """
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    # The model wraps its JSON in some chatter (against instructions) and
    # the chatter contains a stray `{` — a greedy `\{.*\}` matches from
    # that brace through the end and fails to parse.
    bad_then_good = (
        "Here is the page text { which contains a brace } as part of "
        'transcribed prose, then: {"text": "REAL TRANSCRIPTION", "confidence": 88}'
    )
    client = _FakeAnthropic([(bad_then_good, _FakeUsage(800, 30))])
    _patch_client(monkeypatch, client)

    text, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert text == "REAL TRANSCRIPTION"
    assert conf == pytest.approx(88.0)


def test_ocr_image_handles_strict_json_with_braces_in_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even when the model is well-behaved (strict JSON), the transcribed
    text itself may legitimately contain `{` / `}` characters from the
    page. The strict-JSON path must preserve them verbatim.
    """
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    payload = json.dumps({
        "text": "Note: deflection coefficient {k} = 0.42",
        "confidence": 91,
    })
    client = _FakeAnthropic([(payload, _FakeUsage(800, 30))])
    _patch_client(monkeypatch, client)

    text, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert text == "Note: deflection coefficient {k} = 0.42"
    assert conf == pytest.approx(91.0)


# ---------------------------------------------------------------------------
# envelope-artifact recovery (unescaped inner quotes)
# ---------------------------------------------------------------------------
# A class of malformed responses: the model wraps OCR
# text in a JSON envelope (``{"text": "...", "confidence": N}``) but
# leaves inner double-quotes unescaped — typically from stamps or quoted
# names on the source page. ``json.loads`` rejects them; ``raw_decode``
# rejects them; pre-fix, ``_parse_response`` fell through to ``return raw``
# and the literal envelope ended up in the page record. The hotfix script
# (``scripts/repair_altered_ocr_envelopes.py``) is the post-processing
# patch; this is the upstream root-cause fix — every future OCR run.
def test_parse_recovers_envelope_with_unescaped_inner_quotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    # Unescaped " around RECEIVED — the model emitted it verbatim from
    # a stamp on the source page. json.loads fails here; raw_decode too.
    bad_envelope = (
        '{\n  "text": "Date: Jan 12 1968\\nStamp: "RECEIVED" Aug 03",\n'
        '  "confidence": 87\n}'
    )
    client = _FakeAnthropic([(bad_envelope, _FakeUsage(1500, 600))])
    _patch_client(monkeypatch, client)

    text, _ = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert "Date: Jan 12 1968" in text
    assert "RECEIVED" in text
    # Literal envelope must not be returned verbatim.
    assert not text.lstrip().startswith("{")
    assert '"text":' not in text


def test_parse_recovers_envelope_extracts_confidence_from_tail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The envelope's trailing ``"confidence": N`` is well-formed even
    when the inner text isn't. Pull it through rather than defaulting to
    the nominal value."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    bad_envelope = (
        '{\n  "text": "Mr. "Smith" filed a report",\n  "confidence": 63\n}'
    )
    client = _FakeAnthropic([(bad_envelope, _FakeUsage(1500, 600))])
    _patch_client(monkeypatch, client)

    _, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))
    assert conf == pytest.approx(63.0)


def test_parse_recovers_envelope_inside_code_fence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Some malformed envelopes arrive inside a ```json ... ``` fence
    (the model adds the fence against the prompt). Recover those too."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    bad_envelope = (
        '```json\n{\n  "text": "Mr. "Smith" of Air Force",\n'
        '  "confidence": 90\n}\n```'
    )
    client = _FakeAnthropic([(bad_envelope, _FakeUsage(1500, 600))])
    _patch_client(monkeypatch, client)

    text, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert "Smith" in text
    assert "Air Force" in text
    assert "```" not in text
    assert conf == pytest.approx(90.0)


def test_parse_envelope_recovery_unescapes_standard_sequences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recovered text expands ``\\n``, ``\\t``, ``\\r``, ``\\"`` and
    ``\\\\`` — matching what valid JSON parsing would have produced."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    bad_envelope = (
        '{\n  "text": "line 1\\nline 2\\twith "quote"\\rand \\\\path",\n'
        '  "confidence": 75\n}'
    )
    client = _FakeAnthropic([(bad_envelope, _FakeUsage(1500, 600))])
    _patch_client(monkeypatch, client)

    text, _ = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))

    assert "line 1\nline 2" in text  # actual newline
    assert "\t" in text              # actual tab
    assert "\r" in text              # actual carriage return
    assert '"quote"' in text         # the inner unescaped quote survives
    assert "\\path" in text          # \\\\ collapses to \\


def test_parse_response_falls_through_when_envelope_pattern_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pre-existing fallback (raw text + nominal confidence) is preserved
    for truly unstructured responses that don't match the envelope shape."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        ("I cannot transcribe this page.", _FakeUsage(800, 30)),
    ])
    _patch_client(monkeypatch, client)

    text, conf = ocr_llm.ocr_image(Image.new("RGB", (10, 10)))
    assert text == "I cannot transcribe this page."
    assert conf == pytest.approx(75.0)  # _NOMINAL_CONFIDENCE


# ---------------------------------------------------------------------------
# ocr_image_with_usage returns real token counts
# ---------------------------------------------------------------------------
# scripts/reocr_altered.py previously estimated 1500/600 tokens per page
# (~21% under-counted vs reality). Expose actual usage so the cost cap
# stays load-bearing.
def test_ocr_image_with_usage_returns_real_token_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        (_structured_response("page text", 90),
         _FakeUsage(1820, 743, cache_read_input_tokens=512,
                    cache_creation_input_tokens=128)),
    ])
    _patch_client(monkeypatch, client)

    text, conf, usage = ocr_llm.ocr_image_with_usage(Image.new("RGB", (10, 10)))

    assert text == "page text"
    assert conf == pytest.approx(90.0)
    assert usage == {
        "input_tokens": 1820,
        "output_tokens": 743,
        "cache_read_tokens": 512,
        "cache_creation_tokens": 128,
    }


def test_ocr_image_with_usage_returns_zero_for_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cache hits spend zero tokens. The tracker must see zeros so cost
    estimates don't double-count cached pages."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        (_structured_response("cached", 88), _FakeUsage(1500, 500)),
    ])
    _patch_client(monkeypatch, client)

    img = Image.new("RGB", (16, 16), color=(7, 8, 9))
    # First call: real API hit, real usage.
    _, _, first_usage = ocr_llm.ocr_image_with_usage(img)
    assert first_usage["input_tokens"] == 1500

    # Second call with identical image: cache hit, zero usage.
    text, conf, usage = ocr_llm.ocr_image_with_usage(img)
    assert text == "cached"
    assert conf == pytest.approx(88.0)
    assert usage == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }
    # Only one underlying API call.
    assert len(client.messages.calls) == 1
