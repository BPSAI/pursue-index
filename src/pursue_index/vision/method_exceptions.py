"""Cards that stay on their curated passes: a deliberate method exception.

``data/vision-method-exceptions.json`` lists cards whose existing pass was made
by a curated method (the multi-frame study), not by an older model. A
``--redescribe`` would replace that pass with a single-image one, so it refuses
those cards unless the operator overrides it and says why.

The loader fails closed: a missing or malformed file raises
``MethodExceptionsError``, and the caller refuses the run rather than treating
the list as empty.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pursue_index.paths import repo_root
from pursue_index.vision.sidecar import is_card_id

_FIELDS = ("card_id", "reason", "cluster_label", "decided_at")
_FILE = Path("data") / "vision-method-exceptions.json"


class MethodExceptionsError(ValueError):
    """The exceptions file is missing or malformed."""


@dataclass(frozen=True)
class MethodException:
    card_id: str
    reason: str
    cluster_label: str
    decided_at: str


def default_exceptions_path() -> Path:
    """The committed file, under ``repo_root()`` like the other committed ``data/`` files."""
    return repo_root() / _FILE


def _entry(raw: object, where: str) -> MethodException:
    if not isinstance(raw, dict):
        raise MethodExceptionsError(f"{where}: entry is not an object")
    values: dict[str, str] = {}
    for key in _FIELDS:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MethodExceptionsError(f"{where}: {key!r} must be a non-empty string")
        values[key] = value
    if not is_card_id(values["card_id"]):
        raise MethodExceptionsError(
            f"{where}: card_id {values['card_id']!r} is not 16 lowercase hex characters"
        )
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["decided_at"]):
            raise ValueError("shape")
        date.fromisoformat(values["decided_at"])
    except ValueError:
        raise MethodExceptionsError(
            f"{where}: decided_at {values['decided_at']!r} is not an ISO date (YYYY-MM-DD)"
        ) from None
    return MethodException(**values)


def load_method_exceptions(path: Path | None = None) -> list[MethodException]:
    """The listed exceptions; raises ``MethodExceptionsError`` on any defect."""
    path = path or default_exceptions_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MethodExceptionsError(f"{path}: cannot be read as JSON ({exc})") from exc
    rows = data.get("exceptions") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise MethodExceptionsError(f"{path}: needs a non-empty 'exceptions' list")
    entries = [_entry(row, f"{path} entry {n}") for n, row in enumerate(rows)]
    ids = [e.card_id for e in entries]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise MethodExceptionsError(f"{path}: duplicate card_id(s) {duplicates}")
    return entries
