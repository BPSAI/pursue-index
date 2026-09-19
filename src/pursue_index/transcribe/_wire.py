"""Shared basics of the direct AssemblyAI calls: base URL, auth, and the
deadline for a small request. Split out so ``client`` and ``recovery`` can both
use them without importing each other."""

from __future__ import annotations

import os

from pursue_index.transcribe.errors import ApiKeyMissingError

BASE_URL = "https://api.assemblyai.com/v2"
# Poll and list exchange a few hundred bytes and answer quickly.
DEFAULT_REQUEST_TIMEOUT_S = 60.0


def api_key() -> str:
    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        raise ApiKeyMissingError("ASSEMBLYAI_API_KEY not set")
    return key


def headers(key: str) -> dict[str, str]:
    return {"authorization": key}
