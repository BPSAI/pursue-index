"""Recovery of a job whose submit call timed out.

A submit that times out may still have created the transcript on AssemblyAI's
side. Rather than raise and re-pay, the client looks the job up by the upload
URL it just used (unique to one upload) and adopts it.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from pursue_index import get_logger
from pursue_index.transcribe._wire import (
    BASE_URL,
    DEFAULT_REQUEST_TIMEOUT_S,
    headers,
)
from pursue_index.transcribe._wire import api_key as resolve_api_key
from pursue_index.transcribe.errors import SubmitError

log = get_logger(__name__)

HttpGet = Callable[..., httpx.Response]

# A submit that times out may still have created the job; the transcript can
# take a moment to become listable, so the lookup is retried a few times.
_ADOPT_LIST_ATTEMPTS = 3
_ADOPT_LIST_LIMIT = 50


def find_submitted_transcript(
    upload_url: str,
    *,
    api_key: str | None = None,
    get: HttpGet = httpx.get,
    timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> str | None:
    """Id of a recent transcript whose ``audio_url`` is ``upload_url``, else ``None``.

    An upload URL is unique to one upload, so a match is the job this run's
    submit created even though its answer never arrived.
    """
    key = api_key or resolve_api_key()
    resp = get(
        f"{BASE_URL}/transcript",
        headers=headers(key),
        params={"limit": _ADOPT_LIST_LIMIT},
        timeout=timeout_s,
    )
    if resp.status_code != 200:
        raise SubmitError(f"list failed: HTTP {resp.status_code}")
    for item in resp.json().get("transcripts") or []:
        if item.get("audio_url") == upload_url and item.get("id"):
            return str(item["id"])
    return None


def adopt_timed_out_submit(
    upload_url: str,
    *,
    key: str,
    get: HttpGet,
    sleep: Callable[[float], None],
    poll_interval_s: float,
) -> str | None:
    """Look up the job a timed-out submit created; ``None`` if none is found.

    A failed lookup counts as "not found" for that attempt — the caller raises
    the original timeout either way, so this never masks it.
    """
    for attempt in range(_ADOPT_LIST_ATTEMPTS):
        if attempt:
            sleep(poll_interval_s)
        try:
            found = find_submitted_transcript(upload_url, api_key=key, get=get)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            log.warning("transcribe.submit.adopt_lookup_failed", error=type(exc).__name__)
            continue
        if found is not None:
            return found
    return None
