"""Request deadlines on the direct AssemblyAI calls.

Every call in the transcribe stage states the deadline it expects to
finish within, rather than inheriting the HTTP library's default. The
upload is the one that matters most: it sends a whole A/V asset -- tens of
megabytes -- in a single request, so its deadline is sized for the body to
go out over an ordinary link rather than for a round trip.

A submit that times out is not a lost job: the request may have reached
AssemblyAI and created the transcript even though no answer came back. So a
submit timeout looks the job up by the just-uploaded URL and adopts it,
rather than raising and orphaning paid work.

Split from ``test_transcribe_client.py`` (which covers the upload/submit/
poll contract itself) so each file stays a readable size.
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

    assert submit_captured["timeout"] == client.DEFAULT_SUBMIT_TIMEOUT_S
    assert poll_captured["timeout"] == client.DEFAULT_REQUEST_TIMEOUT_S


def test_submit_timeout_is_larger_than_a_status_round_trip() -> None:
    """Submit can take AssemblyAI well over a minute on a large upload, so it
    has its own, larger deadline rather than sharing the poll one."""
    assert client.DEFAULT_SUBMIT_TIMEOUT_S >= 300.0
    assert client.DEFAULT_SUBMIT_TIMEOUT_S > client.DEFAULT_REQUEST_TIMEOUT_S


def test_submit_timeout_is_caller_settable() -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured.update(kwargs)
        return _resp(200, {"id": "t-1"})

    client.submit_transcript(
        "https://cdn.aai/u", multichannel=False, api_key="k", post=fake_post, timeout_s=77.0
    )
    assert captured["timeout"] == 77.0


# --- a timed-out submit is recovered, not repaid ---------------------------

_UPLOAD_URL = "https://cdn.aai/upload/abc"


def _file(tmp_path: Path) -> Path:
    p = tmp_path / "a.mp4"
    p.write_bytes(b"fake mp4 bytes")
    return p


def _completed(text: str = "hello") -> dict:
    return {
        "status": "completed",
        "audio_duration": 3.0,
        "multichannel": False,
        "utterances": [{"speaker": "A", "text": text, "start": 0, "end": 100}],
    }


def test_find_submitted_transcript_matches_on_audio_url() -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return _resp(
            200,
            {
                "transcripts": [
                    {"id": "other", "audio_url": "https://cdn.aai/upload/zzz"},
                    {"id": "mine-12345", "audio_url": _UPLOAD_URL},
                ]
            },
        )

    found = client.find_submitted_transcript(_UPLOAD_URL, api_key="k", get=fake_get)

    assert found == "mine-12345"
    assert str(captured["url"]).endswith("/v2/transcript")
    assert captured["timeout"] == client.DEFAULT_REQUEST_TIMEOUT_S
    assert "limit" in dict(captured["params"])  # type: ignore[call-overload]


def test_find_submitted_transcript_none_when_no_match() -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"transcripts": [{"id": "x", "audio_url": "https://cdn.aai/o"}]})

    assert client.find_submitted_transcript(_UPLOAD_URL, api_key="k", get=fake_get) is None


def test_submit_timeout_lists_adopts_and_polls_the_created_job(tmp_path: Path) -> None:
    """Timeout -> list -> adopt -> poll: the job AssemblyAI already created is
    the one polled, and no second submit is made."""
    calls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            calls.append("upload")
            return _resp(200, {"upload_url": _UPLOAD_URL})
        calls.append("submit")
        raise httpx.ReadTimeout("timed out")

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/transcript"):
            calls.append("list")
            return _resp(
                200, {"transcripts": [{"id": "orphan-12345", "audio_url": _UPLOAD_URL}]}
            )
        calls.append(f"poll:{url.rsplit('/', 1)[-1]}")
        return _resp(200, _completed())

    result = client.transcribe_file(
        _file(tmp_path), multichannel=False, api_key="k", post=fake_post, get=fake_get,
        sleep=lambda s: None,
    )

    assert calls == ["upload", "submit", "list", "poll:orphan-12345"]
    assert [u["text"] for u in result.utterances] == ["hello"]


def test_submit_timeout_retries_the_list_before_giving_up(tmp_path: Path) -> None:
    """The job can take a moment to become listable after the timeout."""
    lists = {"n": 0}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            return _resp(200, {"upload_url": _UPLOAD_URL})
        raise httpx.ReadTimeout("timed out")

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/transcript"):
            lists["n"] += 1
            found = [{"id": "late-12345", "audio_url": _UPLOAD_URL}] if lists["n"] >= 2 else []
            return _resp(200, {"transcripts": found})
        return _resp(200, _completed())

    result = client.transcribe_file(
        _file(tmp_path), multichannel=False, api_key="k", post=fake_post, get=fake_get,
        sleep=lambda s: None,
    )
    assert lists["n"] == 2
    assert result.utterances


def test_submit_timeout_with_no_matching_job_raises_submit_error(tmp_path: Path) -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            return _resp(200, {"upload_url": _UPLOAD_URL})
        raise httpx.ReadTimeout("timed out")

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(200, {"transcripts": []})

    with pytest.raises(client.SubmitError, match="timed out"):
        client.transcribe_file(
            _file(tmp_path), multichannel=False, api_key="k", post=fake_post, get=fake_get,
            sleep=lambda s: None,
        )


def test_submit_timeout_when_the_lookup_also_fails_raises_submit_error(
    tmp_path: Path,
) -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            return _resp(200, {"upload_url": _UPLOAD_URL})
        raise httpx.ReadTimeout("timed out")

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectTimeout("no route")

    with pytest.raises(client.SubmitError, match="timed out"):
        client.transcribe_file(
            _file(tmp_path), multichannel=False, api_key="k", post=fake_post, get=fake_get,
            sleep=lambda s: None,
        )


def test_non_timeout_submit_failure_is_not_recovered_by_listing(tmp_path: Path) -> None:
    """An HTTP error answer means the job was refused; only a timeout leaves the
    outcome unknown."""
    listed: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "upload" in url:
            return _resp(200, {"upload_url": _UPLOAD_URL})
        return _resp(500)

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        listed.append(url)
        return _resp(200, {"transcripts": []})

    with pytest.raises(client.SubmitError, match="HTTP 500"):
        client.transcribe_file(
            _file(tmp_path), multichannel=False, api_key="k", post=fake_post, get=fake_get,
            sleep=lambda s: None,
        )
    assert listed == []


def test_find_submitted_transcript_rejects_a_malformed_listed_id() -> None:
    """An id that is not an opaque token never reaches a poll URL."""
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return _resp(
            200, {"transcripts": [{"id": "../../x/../y1234", "audio_url": _UPLOAD_URL}]}
        )

    with pytest.raises(client.InvalidJobIdError):
        client.find_submitted_transcript(_UPLOAD_URL, api_key="k", get=fake_get)
