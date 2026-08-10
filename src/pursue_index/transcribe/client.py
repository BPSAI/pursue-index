"""Direct AssemblyAI client — own key, bounded poll, small error taxonomy.

Built directly against AssemblyAI's public REST API (upload, submit, poll)
via ``httpx``, using OUR OWN ``ASSEMBLYAI_API_KEY`` — never any Aurora
service path. Crib note: mirrors the shape of a bounded-poll batch
transcription client (submit -> poll with a hard wall-clock timeout -> map
terminal states to a small error taxonomy) without importing Aurora code;
this is an independent implementation against AAI's documented REST
endpoints, exercised in tests only through injected ``post``/``get``/
``sleep``/``now`` seams — no live call, no ``assemblyai`` SDK dependency.

The mp4 uploads AS-IS (no audio-extraction step) — ``upload_audio`` sends
the file's raw bytes unchanged.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from pursue_index import get_logger

log = get_logger(__name__)

_BASE_URL = "https://api.assemblyai.com/v2"
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_POLL_TIMEOUT_S = 1800.0  # 30 min hard cap — never polls forever

# Every request states the deadline it expects to finish within, so no call
# in this stage inherits an HTTP-library default sized for small JSON.
# Submit and poll exchange a few hundred bytes and answer quickly.
DEFAULT_REQUEST_TIMEOUT_S = 60.0
# The upload sends a whole A/V asset — tens of megabytes — in one request,
# so its deadline is sized for the body to go out over an ordinary link
# rather than for a round trip.
DEFAULT_UPLOAD_TIMEOUT_S = 1800.0


class TranscribeError(Exception):
    """Base of the AAI client's error taxonomy."""


class ApiKeyMissingError(TranscribeError):
    """``ASSEMBLYAI_API_KEY`` isn't set in the environment."""


class UploadError(TranscribeError):
    """The upload request failed or returned an unusable response."""


class SubmitError(TranscribeError):
    """Job submission/status-poll HTTP call failed or was malformed."""


class PollTimeoutError(TranscribeError):
    """Polling exceeded the hard timeout before reaching a terminal state."""


class TranscriptFailedError(TranscribeError):
    """AssemblyAI itself reported the transcript job as failed."""


@dataclass(frozen=True)
class TranscriptResult:
    """A completed transcript, normalized for the sidecar writer."""

    utterances: list[dict[str, Any]]
    audio_duration_s: float | None
    speakers: list[str]
    multichannel: bool
    raw: dict[str, Any]


HttpPost = Callable[..., httpx.Response]
HttpGet = Callable[..., httpx.Response]


def _api_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        raise ApiKeyMissingError("ASSEMBLYAI_API_KEY not set")
    return key


def _headers(key: str) -> dict[str, str]:
    return {"authorization": key}


def upload_audio(
    path: Path,
    *,
    api_key: str | None = None,
    post: HttpPost = httpx.post,
    timeout_s: float = DEFAULT_UPLOAD_TIMEOUT_S,
) -> str:
    """Upload ``path``'s bytes as-is; return the AAI-hosted ``upload_url``.

    ``timeout_s`` covers sending the entire asset body, so it is stated
    explicitly and defaults generously; a caller on a slower link can widen
    it further.
    """
    key = api_key or _api_key()
    resp = post(
        f"{_BASE_URL}/upload",
        headers=_headers(key),
        content=path.read_bytes(),
        timeout=timeout_s,
    )
    if resp.status_code != 200:
        raise UploadError(f"upload failed: HTTP {resp.status_code}")
    upload_url = resp.json().get("upload_url")
    if not upload_url:
        raise UploadError("upload response missing upload_url")
    return str(upload_url)


def submit_transcript(
    upload_url: str,
    *,
    multichannel: bool,
    api_key: str | None = None,
    post: HttpPost = httpx.post,
    timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> str:
    """Submit a diarized transcription job; return the transcript id."""
    key = api_key or _api_key()
    payload = {
        "audio_url": upload_url,
        "speaker_labels": True,
        "multichannel": multichannel,
    }
    resp = post(
        f"{_BASE_URL}/transcript",
        headers=_headers(key),
        json=payload,
        timeout=timeout_s,
    )
    if resp.status_code != 200:
        raise SubmitError(f"submit failed: HTTP {resp.status_code}")
    transcript_id = resp.json().get("id")
    if not transcript_id:
        raise SubmitError("submit response missing id")
    return str(transcript_id)


def poll_transcript(
    transcript_id: str,
    *,
    api_key: str | None = None,
    get: HttpGet = httpx.get,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll until ``completed``/``error`` or the hard timeout.

    ``timeout_s`` is a wall-clock deadline enforced every iteration — this
    never polls forever, even if AAI's job status never reaches a terminal
    state.
    """
    key = api_key or _api_key()
    deadline = now() + timeout_s
    while True:
        resp = get(
            f"{_BASE_URL}/transcript/{transcript_id}",
            headers=_headers(key),
            timeout=request_timeout_s,
        )
        if resp.status_code != 200:
            raise SubmitError(f"poll failed: HTTP {resp.status_code}")
        data: dict[str, Any] = resp.json()
        status = data.get("status")
        if status == "completed":
            return data
        if status == "error":
            raise TranscriptFailedError(str(data.get("error") or "unknown AAI error"))
        if now() >= deadline:
            raise PollTimeoutError(
                f"transcript {transcript_id} did not complete within {timeout_s}s"
            )
        sleep(poll_interval_s)


def _parse_utterances(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u in data.get("utterances") or []:
        out.append(
            {
                "speaker": str(u.get("speaker")) if u.get("speaker") is not None else "",
                "text": u.get("text", ""),
                "start": u.get("start"),
                "end": u.get("end"),
                "channel": str(u["channel"]) if u.get("channel") is not None else None,
            }
        )
    return out


def transcribe_file(
    path: Path,
    *,
    multichannel: bool,
    api_key: str | None = None,
    post: HttpPost = httpx.post,
    get: HttpGet = httpx.get,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> TranscriptResult:
    """Upload -> submit -> bounded-poll one mp4. Uploads the file as-is (no
    audio-extraction step); ``multichannel`` is decided by the caller (a
    channel probe), never guessed here."""
    key = api_key or _api_key()
    upload_url = upload_audio(path, api_key=key, post=post)
    transcript_id = submit_transcript(
        upload_url, multichannel=multichannel, api_key=key, post=post
    )
    log.info("transcribe.submitted", transcript_id=transcript_id, multichannel=multichannel)
    data = poll_transcript(
        transcript_id, api_key=key, get=get,
        poll_interval_s=poll_interval_s, timeout_s=timeout_s, sleep=sleep,
    )
    utterances = _parse_utterances(data)
    speakers = sorted({u["speaker"] for u in utterances if u["speaker"]})
    return TranscriptResult(
        utterances=utterances,
        audio_duration_s=data.get("audio_duration"),
        speakers=speakers,
        multichannel=multichannel,
        raw=data,
    )
