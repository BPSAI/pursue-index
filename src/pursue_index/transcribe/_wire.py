"""Shared basics of the direct AssemblyAI calls: base URL, auth, and the
deadline for a small request. Split out so ``client`` and ``recovery`` can both
use them without importing each other."""

from __future__ import annotations

import os
import re

from pursue_index.transcribe.errors import ApiKeyMissingError, InvalidJobIdError

BASE_URL = "https://api.assemblyai.com/v2"
# Poll and list exchange a few hundred bytes and answer quickly.
DEFAULT_REQUEST_TIMEOUT_S = 60.0

# AssemblyAI transcript ids are opaque UUID-like tokens. The id is interpolated
# into a request path, so anything else (slashes, ``?``, ``..``, spaces) is refused.
_JOB_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,128}")


def is_valid_job_id(job_id: str) -> bool:
    return _JOB_ID_RE.fullmatch(job_id) is not None


def require_job_id(job_id: str) -> str:
    """Return ``job_id`` if it is an opaque token; raise ``InvalidJobIdError`` otherwise."""
    if not is_valid_job_id(job_id):
        raise InvalidJobIdError("transcript id must match [A-Za-z0-9_-]{8,128}")
    return job_id


def api_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        raise ApiKeyMissingError("ASSEMBLYAI_API_KEY not set")
    return key


def headers(key: str) -> dict[str, str]:
    return {"authorization": key}
