"""Direct AssemblyAI client — own key, bounded poll, small error taxonomy.

Built against AssemblyAI's public REST API (upload, submit, poll) via
``httpx``, authenticated with this project's own ``ASSEMBLYAI_API_KEY``. The
three calls are the whole surface, so the SDK would add a dependency without
adding capability; going straight to the documented endpoints also keeps the
seams injectable. Batch transcription is asynchronous, so the client submits,
then polls under two independent bounds — a wall-clock deadline and a retry
budget — and maps terminal states to a small error taxonomy the run layer can
report per row.

Tests drive it entirely through injected ``post``/``get``/``sleep``/``now``
seams: no live call, and no ``assemblyai`` SDK dependency.

The mp4 uploads AS-IS (no audio-extraction step) — ``upload_audio`` sends
the file's raw bytes unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from pursue_index import get_logger
from pursue_index.transcribe import _wire
from pursue_index.transcribe._wire import DEFAULT_REQUEST_TIMEOUT_S

# The error taxonomy and ``TranscriptResult`` live in their own modules and are
# re-exported here: ``client`` is the surface callers import them from.
from pursue_index.transcribe.errors import (  # noqa: F401
    ApiKeyMissingError,
    InvalidJobIdError,
    PollTimeoutError,
    SubmitError,
    TranscribeError,
    TranscriptFailedError,
    UploadError,
)
from pursue_index.transcribe.recovery import (  # noqa: F401
    adopt_timed_out_submit,
    find_submitted_transcript,
)
from pursue_index.transcribe.result import TranscriptResult, result_from

log = get_logger(__name__)

_BASE_URL = _wire.BASE_URL
_api_key = _wire.api_key
_headers = _wire.headers

DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_POLL_TIMEOUT_S = 1800.0  # 30 min hard cap — never polls forever
# Consecutive unusable status answers tolerated before polling gives up. A
# submitted job's status endpoint answers many times over the job's life, so
# this is sized to ride out a short interruption while still ending on a
# persistent one; the wall-clock deadline bounds the total either way.
DEFAULT_MAX_POLL_RETRIES = 5

# Every request states the deadline it expects to finish within, so no call
# in this stage inherits an HTTP-library default sized for small JSON.
# Poll and list exchange a few hundred bytes and answer quickly.
# Submit is a small request too, but AssemblyAI can take well over a minute to
# answer it for a large upload; a deadline sized for a status round trip cut it
# off after the job already existed. It gets its own, larger bound.
DEFAULT_SUBMIT_TIMEOUT_S = 300.0
# The upload sends a whole A/V asset — tens of megabytes — in one request,
# so its deadline is sized for the body to go out over an ordinary link
# rather than for a round trip.
DEFAULT_UPLOAD_TIMEOUT_S = 1800.0


HttpPost = Callable[..., httpx.Response]
HttpGet = Callable[..., httpx.Response]


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
    timeout_s: float = DEFAULT_SUBMIT_TIMEOUT_S,
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


def _poll_once(
    transcript_id: str,
    key: str,
    get: HttpGet,
    request_timeout_s: float,
) -> tuple[dict[str, Any] | None, str | None]:
    """One status request. Returns ``(data, reason)``; exactly one is set.

    ``reason`` states why an answer was unusable — an unexpected status code
    or a transport-level failure — so the caller can spend a retry against it
    and, once the budget is gone, report what it was spent on.
    """
    try:
        resp = get(
            f"{_BASE_URL}/transcript/{transcript_id}",
            headers=_headers(key),
            timeout=request_timeout_s,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        return None, f"poll failed: {type(exc).__name__}"
    if resp.status_code != 200:
        return None, f"poll failed: HTTP {resp.status_code}"
    return dict(resp.json()), None


def poll_transcript(
    transcript_id: str,
    *,
    api_key: str | None = None,
    get: HttpGet = httpx.get,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    max_poll_retries: int = DEFAULT_MAX_POLL_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll until ``completed``/``error``, the retry budget, or the deadline.

    Two independent bounds apply, and neither substitutes for the other:

    * ``timeout_s`` is a wall-clock deadline enforced every iteration — this
      never polls forever, even if the job's status never reaches a terminal
      state.
    * ``max_poll_retries`` bounds consecutive unusable status answers. The job
      is already submitted and its status endpoint answers many times over its
      life, so one unusable answer part-way through is not a reason to drop
      it. The budget resets on every usable answer and, once spent, the last
      reason is raised.
    """
    key = api_key or _api_key()
    deadline = now() + timeout_s
    retries_left = max_poll_retries
    while True:
        data, reason = _poll_once(transcript_id, key, get, request_timeout_s)
        if reason is not None:
            if retries_left <= 0:
                raise SubmitError(reason)
            retries_left -= 1
            log.warning(
                "transcribe.poll.retrying",
                transcript_id=transcript_id, reason=reason, retries_left=retries_left,
            )
        else:
            retries_left = max_poll_retries
            assert data is not None
            status = data.get("status")
            if status == "completed":
                return data
            if status == "error":
                raise TranscriptFailedError(
                    str(data.get("error") or "unknown AAI error")
                )
        if now() >= deadline:
            raise PollTimeoutError(
                f"transcript {transcript_id} did not complete within {timeout_s}s"
            )
        sleep(poll_interval_s)


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
    channel probe), never guessed here.

    If the submit call times out, the job may already exist on AssemblyAI's
    side, so it is looked up by the upload URL and polled rather than raised
    and re-paid; only when no such job is found does the timeout surface.
    """
    key = api_key or _api_key()
    upload_url = upload_audio(path, api_key=key, post=post)
    try:
        transcript_id = submit_transcript(
            upload_url, multichannel=multichannel, api_key=key, post=post
        )
    except httpx.TimeoutException as exc:
        adopted = adopt_timed_out_submit(
            upload_url, key=key, get=get, sleep=sleep, poll_interval_s=poll_interval_s
        )
        if adopted is None:
            raise SubmitError(
                "submit timed out and no job was found for the uploaded audio"
            ) from exc
        log.warning("transcribe.submit.adopted_after_timeout", transcript_id=adopted)
        transcript_id = adopted
    log.info("transcribe.submitted", transcript_id=transcript_id, multichannel=multichannel)
    data = poll_transcript(
        transcript_id, api_key=key, get=get,
        poll_interval_s=poll_interval_s, timeout_s=timeout_s, sleep=sleep,
    )
    return result_from(data, multichannel=multichannel)


def resume_transcript(
    transcript_id: str,
    *,
    api_key: str | None = None,
    get: HttpGet = httpx.get,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> TranscriptResult:
    """Poll an already-submitted job to completion — no upload, no submit.

    The manual recovery path for a job whose submit answer was lost. The
    ``multichannel`` reported is the one the job actually ran with, read back
    from AssemblyAI rather than assumed. ``transcript_id`` must be an opaque
    token (``InvalidJobIdError`` otherwise); it is checked before any request.
    """
    _wire.require_job_id(transcript_id)
    key = api_key or _api_key()
    data = poll_transcript(
        transcript_id, api_key=key, get=get,
        poll_interval_s=poll_interval_s, timeout_s=timeout_s, sleep=sleep,
    )
    return result_from(data, multichannel=bool(data.get("multichannel")))
