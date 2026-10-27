"""Write a tranche-ready record: schema-checked first, append-only per sha.

Producer-side guard (R7C.31): :func:`check_record` validates against the
vendored schema and raises :class:`InvalidRecordError` naming the first
failing field, so an invalid record is never written -- the poll job exits
non-zero and its failure issue carries that field name.

Append-only, the contract ``scripts/poll_snapshot.py`` already applies to
its diff records: a stored record is the record as first observed.
An equal recompute is a no-op; a disagreeing one raises
:class:`AppendOnlyError` (stored vs recomputed in the message) and writes
nothing. Equality ignores ``VOLATILE_FIELDS`` -- when and by which run the
record was produced, which every re-run changes -- and nothing else.

:func:`needs_write` is the same check with no side effect, so a caller that
writes several files can check them all before writing any.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pursue_index.tranche_ready.refusal import describe_conflict, full_diff
from pursue_index.tranche_ready.schema import SchemaError, load_schema, validate

__all__ = ["VOLATILE_FIELDS", "AppendOnlyError", "InvalidRecordError", "check_record",
           "needs_write", "write_record"]

VOLATILE_FIELDS = ("detected_at", "generated_at", "generated_by")


class InvalidRecordError(ValueError):
    """The record does not validate; ``field`` is the first failing field."""

    def __init__(self, errors: list[SchemaError]) -> None:
        self.errors = errors
        self.field = errors[0].field
        detail = "; ".join(str(e) for e in errors[:10])
        super().__init__(f"tranche-ready record is invalid at field '{self.field}': {detail}")


class AppendOnlyError(RuntimeError):
    """A record already exists for this sha and the recompute disagrees.

    The message is value-free (it is filed as a public issue); the full
    records stay on the exception for a local file via :meth:`full_diff`.
    """

    def __init__(self, message: str, stored: Any = None, recomputed: Any = None) -> None:
        super().__init__(message)
        self.stored, self.recomputed = stored, recomputed

    def full_diff(self) -> str:
        return full_diff(self.stored, self.recomputed)


def check_record(record: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    """Raise :class:`InvalidRecordError` unless ``record`` validates."""
    errors = validate(record, schema if schema is not None else load_schema())
    if errors:
        raise InvalidRecordError(errors)


def _content(doc: Any, ignore: tuple[str, ...]) -> Any:
    return {k: v for k, v in doc.items() if k not in ignore} if isinstance(doc, dict) else doc


def needs_write(path: Path, doc: Any, *, ignore: tuple[str, ...] = VOLATILE_FIELDS) -> bool:
    """``True`` when ``path`` is absent, ``False`` when it holds an equal
    document; :class:`AppendOnlyError` when it holds a different one."""
    if not path.exists():
        return True
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = None
    if _content(stored, ignore) == _content(doc, ignore):
        return False
    stored_c, doc_c = _content(stored, ignore), _content(doc, ignore)
    raise AppendOnlyError(describe_conflict(path, stored_c, doc_c), stored_c, doc_c)


def write_record(
    path: Path, record: dict[str, Any], schema: dict[str, Any] | None = None,
) -> str:
    """Validate, then write unless an equal record is stored.

    Returns ``"written"`` or ``"unchanged"``; raises :class:`InvalidRecordError`
    or :class:`AppendOnlyError` without writing.
    """
    check_record(record, schema)
    if not needs_write(path, record):
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return "written"
