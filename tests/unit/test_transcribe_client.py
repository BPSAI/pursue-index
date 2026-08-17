"""Tests for ``pursue_index.transcribe.client`` — the direct AssemblyAI client.

Covers the key read from ``ASSEMBLYAI_API_KEY``, bounded polling, and the
small error taxonomy that lets a per-row failure in ``transcribe.run`` carry a
clear reason. Every call goes through injected ``post``/``get`` seams — no
real HTTP, no ``assemblyai`` SDK import, no network in tests.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pursue_index.transcribe import client


def _resp(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body or {}, request=httpx.Request("GET", "https://x")
    )


# --- api key -----------------------------------------------------------


def test_api_key_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "own-key-123")
    assert client._api_key() == "own-key-123"


def test_api_key_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSEMBLYAI_API_KEY", raising=False)
    with pytest.raises(client.ApiKeyMissingError):
        client._api_key()


# --- upload_audio --------------------------------------------------------


def test_upload_audio_returns_upload_url(tmp_path: Path) -> None:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"fake mp4 bytes")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return _resp(200, {"upload_url": "https://cdn.aai/upload/abc"})

    result = client.upload_audio(p, api_key="k", post=fake_post)
    assert result == "https://cdn.aai/upload/abc"
    assert captured["headers"] == {"authorization": "k"}
    assert "upload" in str(captured["url"])


def test_upload_audio_raises_on_non_200(tmp_path: Path) -> None:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return _resp(500, {})

    with pytest.raises(client.UploadError):
        client.upload_audio(p, api_key="k", post=fake_post)


def test_upload_audio_raises_when_response_missing_url(tmp_path: Path) -> None:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"x")

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {})

    with pytest.raises(client.UploadError):
        client.upload_audio(p, api_key="k", post=fake_post)


# --- submit_transcript -----------------------------------------------------


def test_submit_transcript_returns_id_and_sends_speaker_labels() -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _resp(200, {"id": "tid-1"})

    tid = client.submit_transcript(
        "https://cdn.aai/upload/abc", multichannel=False, api_key="k", post=fake_post
    )
    assert tid == "tid-1"
    payload = captured["json"]
    assert payload["speaker_labels"] is True
    assert payload["multichannel"] is False
    assert payload["audio_url"] == "https://cdn.aai/upload/abc"


def test_submit_transcript_passes_multichannel_true() -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _resp(200, {"id": "tid-1"})

    client.submit_transcript(
        "https://cdn.aai/upload/abc", multichannel=True, api_key="k", post=fake_post
    )
    assert captured["json"]["multichannel"] is True


def test_submit_transcript_raises_on_non_200() -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return _resp(400, {})

    with pytest.raises(client.SubmitError):
        client.submit_transcript(
            "https://cdn.aai/upload/abc", multichannel=False, api_key="k", post=fake_post
        )


def test_submit_transcript_raises_when_response_missing_id() -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {})

    with pytest.raises(client.SubmitError):
        client.submit_transcript(
            "https://cdn.aai/upload/abc", multichannel=False, api_key="k", post=fake_post
        )


# --- poll_transcript (bounded polling) -----------------------------------


def test_poll_transcript_returns_on_completed() -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"status": "completed", "utterances": []})

    data = client.poll_transcript("tid-1", api_key="k", get=fake_get, sleep=lambda s: None)
    assert data["status"] == "completed"


def test_poll_transcript_polls_until_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = iter(["queued", "processing", "completed"])
    sleeps: list[float] = []

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"status": next(statuses)})

    data = client.poll_transcript(
        "tid-1", api_key="k", get=fake_get, poll_interval_s=1.0,
        sleep=lambda s: sleeps.append(s),
    )
    assert data["status"] == "completed"
    assert sleeps == [1.0, 1.0]


def test_poll_transcript_raises_transcript_failed_error() -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"status": "error", "error": "bad audio format"})

    with pytest.raises(client.TranscriptFailedError, match="bad audio format"):
        client.poll_transcript("tid-1", api_key="k", get=fake_get, sleep=lambda s: None)


def test_poll_transcript_raises_on_non_200() -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(503, {})

    with pytest.raises(client.SubmitError):
        client.poll_transcript("tid-1", api_key="k", get=fake_get, sleep=lambda s: None)


def test_poll_transcript_enforces_hard_timeout() -> None:
    """Never polls forever: exceeding the deadline raises even if the job
    never reaches a terminal state."""
    clock = iter([0.0, 0.0, 5.0, 11.0])  # deadline computed at 10.0

    def fake_now() -> float:
        return next(clock)

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"status": "processing"})

    with pytest.raises(client.PollTimeoutError):
        client.poll_transcript(
            "tid-1", api_key="k", get=fake_get, timeout_s=10.0,
            poll_interval_s=1.0, sleep=lambda s: None, now=fake_now,
        )


# --- transcribe_file (upload -> submit -> poll) ---------------------------


def test_transcribe_file_orchestrates_upload_submit_poll(tmp_path: Path) -> None:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"fake mp4 bytes")
    calls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            calls.append("upload")
            return _resp(200, {"upload_url": "https://cdn.aai/upload/abc"})
        calls.append("submit")
        return _resp(200, {"id": "tid-1"})

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        calls.append("poll")
        return _resp(
            200,
            {
                "status": "completed",
                "audio_duration": 42.5,
                "utterances": [
                    {"speaker": "A", "text": "hello", "start": 0, "end": 100},
                    {"speaker": "A", "text": "there", "start": 100, "end": 200},
                    {"speaker": "B", "text": "hi", "start": 200, "end": 300},
                ],
            },
        )

    result = client.transcribe_file(
        p, multichannel=False, api_key="k", post=fake_post, get=fake_get,
        sleep=lambda s: None,
    )
    assert calls == ["upload", "submit", "poll"]
    assert result.audio_duration_s == 42.5
    assert result.multichannel is False
    assert result.speakers == ["A", "B"]
    assert [u["text"] for u in result.utterances] == ["hello", "there", "hi"]


def test_transcribe_file_uploads_mp4_bytes_unchanged_no_extraction_step(
    tmp_path: Path,
) -> None:
    """The mp4 uploads as-is: the exact bytes on disk are the upload body,
    with no audio-extraction step in between."""
    p = tmp_path / "a.mp4"
    original_bytes = b"\x00\x00\x00\x1cftypM4V some fake mp4 payload"
    p.write_bytes(original_bytes)
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            captured["content"] = kwargs.get("content")
            return _resp(200, {"upload_url": "https://cdn.aai/upload/abc"})
        return _resp(200, {"id": "tid-1"})

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"status": "completed", "utterances": []})

    client.transcribe_file(
        p, multichannel=False, api_key="k", post=fake_post, get=fake_get,
        sleep=lambda s: None,
    )
    assert captured["content"] == original_bytes
