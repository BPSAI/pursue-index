"""Request deadlines on the direct AssemblyAI calls.

Every call in the transcribe stage states the deadline it expects to
finish within, rather than inheriting the HTTP library's default. The
upload is the one that matters most: it sends a whole A/V asset -- tens of
megabytes -- in a single request, so its deadline is sized for the body to
go out over an ordinary link rather than for a round trip.

Split from ``test_transcribe_client.py`` (which covers the upload/submit/
poll contract itself) so each file stays a readable size.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from pursue_index.transcribe import client


def _resp(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code, json=json_body or {}, request=httpx.Request("GET", "https://x")
    )


def test_upload_audio_passes_a_timeout_sized_for_a_whole_asset(
    tmp_path: Path,
) -> None:
    """An A/V asset is tens of megabytes, so the upload states its own
    deadline: long enough for the whole body to go out over an ordinary
    link, rather than inheriting the HTTP library's short default.
    """
    p = tmp_path / "a.mp4"
    p.write_bytes(b"fake mp4 bytes")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _resp(200, {"upload_url": "https://cdn.aai/upload/abc"})

    client.upload_audio(p, api_key="k", post=fake_post)

    assert "timeout" in captured
    assert captured["timeout"] == client.DEFAULT_UPLOAD_TIMEOUT_S
    assert client.DEFAULT_UPLOAD_TIMEOUT_S >= 300.0


def test_upload_audio_timeout_is_caller_settable(tmp_path: Path) -> None:
    """A caller on a known-slow link can widen the upload deadline."""
    p = tmp_path / "a.mp4"
    p.write_bytes(b"fake mp4 bytes")
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _resp(200, {"upload_url": "https://cdn.aai/upload/abc"})

    client.upload_audio(p, api_key="k", post=fake_post, timeout_s=1234.0)

    assert captured["timeout"] == 1234.0


def test_submit_and_poll_state_their_own_request_timeouts() -> None:
    """Every AAI call names the deadline it expects to finish within, so no
    request in the stage relies on a library default."""
    submit_captured: dict[str, object] = {}
    poll_captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        submit_captured.update(kwargs)
        return _resp(200, {"id": "t-1"})

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        poll_captured.update(kwargs)
        return _resp(200, {"status": "completed"})

    client.submit_transcript("https://cdn.aai/u", multichannel=False, api_key="k", post=fake_post)
    client.poll_transcript("t-1", api_key="k", get=fake_get)

    assert submit_captured["timeout"] == client.DEFAULT_REQUEST_TIMEOUT_S
    assert poll_captured["timeout"] == client.DEFAULT_REQUEST_TIMEOUT_S
