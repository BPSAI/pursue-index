"""The vision client's usage log line and request shape (no API call)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image
from structlog.testing import capture_logs

from pursue_index.vision import client


def _fake(reply: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return reply

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(client, "_get_anthropic_client", lambda: fake)
    return seen


def _reply(usage: Any, *, stop_reason: str = "end_turn", content: Any = None) -> Any:
    blocks = content if content is not None else [
        SimpleNamespace(type="text", text='{"description": "x"}')]
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop_reason)


def test_the_usage_log_line_carries_the_cache_token_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = SimpleNamespace(input_tokens=11, output_tokens=7,
                            cache_creation_input_tokens=5, cache_read_input_tokens=3)
    _fake(_reply(usage), monkeypatch)
    with capture_logs() as logs:
        client.examine_image(Image.new("RGB", (8, 8)))
    (line,) = [e for e in logs if e["event"] == "vision.usage"]
    assert line["cache_creation_input_tokens"] == 5
    assert line["cache_read_input_tokens"] == 3


def test_missing_cache_counts_log_as_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = SimpleNamespace(input_tokens=11, output_tokens=7,
                            cache_creation_input_tokens=None)
    _fake(_reply(usage), monkeypatch)
    with capture_logs() as logs:
        client.examine_image(Image.new("RGB", (8, 8)))
    (line,) = [e for e in logs if e["event"] == "vision.usage"]
    assert line["cache_creation_input_tokens"] == 0
    assert line["cache_read_input_tokens"] == 0


def test_the_system_block_carries_no_cache_marker() -> None:
    request = client._build_request("aGk=", "claude-opus-4-8")
    (block,) = request["system"]
    assert "cache_control" not in block
    assert block["text"] == client._SYSTEM_PROMPT


def test_default_max_tokens_is_unchanged_and_overridable() -> None:
    assert client._build_request("aGk=", "m")["max_tokens"] == 2048
    assert client._build_request("aGk=", "m", max_tokens=9000)["max_tokens"] == 9000


def test_effort_is_sent_only_when_asked_for() -> None:
    assert "output_config" not in client._build_request("aGk=", "m")
    req = client._build_request("aGk=", "m", effort="low")
    assert req["output_config"] == {"effort": "low"}


def test_examine_image_forwards_overrides_and_reports_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _fake(_reply(SimpleNamespace(input_tokens=1, output_tokens=1),
                        stop_reason="max_tokens"), monkeypatch)
    result = client.examine_image(Image.new("RGB", (8, 8)), model="m", max_tokens=5000)
    assert seen[0]["max_tokens"] == 5000
    assert result["_stop_reason"] == "max_tokens"


def test_a_thinking_block_ahead_of_the_text_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = [SimpleNamespace(type="thinking", thinking="hmm"),
               SimpleNamespace(type="text", text='{"description": "seen"}')]
    _fake(_reply(SimpleNamespace(input_tokens=1, output_tokens=1), content=content),
          monkeypatch)
    assert client.examine_image(Image.new("RGB", (8, 8)))["description"] == "seen"


def test_the_stop_reason_never_reaches_the_sidecar(tmp_path: Any) -> None:
    import json
    from pathlib import Path

    from pursue_index.vision.eligibility import EligibleItem
    from pursue_index.vision.run import run_vision

    item = EligibleItem(card_id="c0", page=1, kind="img_card",
                        image_path=Path("/x"), title="T", row_key="")

    def examine(_img: object) -> dict[str, Any]:
        return {"image_type": "p", "description": "d", "visible_text": "",
                "observations": [], "_stop_reason": "end_turn"}

    run_vision([item], tmp_path, examine_fn=examine, load_image_fn=lambda _i: object())
    page = json.loads((tmp_path / "c0.json").read_text())["pages"][0]
    assert "_stop_reason" not in page
