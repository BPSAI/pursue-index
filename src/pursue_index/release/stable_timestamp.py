"""Keep a payload's build timestamp when nothing else in it changed.

Derived payloads carry a ``generated_at`` field. Rewriting it on every build
makes a release diff show files whose content did not change, so a builder
passes its new payload through :func:`keep_unchanged_timestamp` before
writing: if the file on disk holds the same payload apart from that field,
the old timestamp is kept and the bytes stay identical.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIELD = "generated_at"


def keep_unchanged_timestamp(out_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` with the existing file's ``generated_at`` if all else matches.

    A missing, unreadable or non-object file, or one without a string
    ``generated_at``, leaves ``payload`` as it is.
    """
    try:
        existing = json.loads(out_path.read_text())
    except (OSError, ValueError):
        return payload
    if not isinstance(existing, dict) or not isinstance(existing.get(FIELD), str):
        return payload
    rest = {k: v for k, v in payload.items() if k != FIELD}
    if {k: v for k, v in existing.items() if k != FIELD} != rest:
        return payload
    return {**payload, FIELD: existing[FIELD]}
