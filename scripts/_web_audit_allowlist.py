"""Allowlist validation for scripts/web_audit_gate.py.

Standard library only, loaded by path from beside the gate (see the gate's
``_load_sibling``): the gate runs as a bare ``python3 -I``.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path


def review_date(value: object, where: str) -> datetime.date:
    if not isinstance(value, str):
        raise ValueError(f"{where} needs a review_by date (YYYY-MM-DD)")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{where} review_by must be a YYYY-MM-DD date, got {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{where} review_by is not a real date: {value!r}") from None


_NAME_VERSION = r"(@[^/@\s]+/)?[^/@\s]+@[^@\s]+"


def _reason_ok(entry: object) -> bool:
    return isinstance(entry, str) and bool(entry.strip())


def _check_build_only(name: str, entry: object) -> None:
    if not _reason_ok(entry):
        raise ValueError(f"build_only[{name!r}] needs a reason")
    if not re.fullmatch(_NAME_VERSION, name):
        raise ValueError(
            f"build_only[{name!r}] must be an exact name@version "
            "(a bare package name is the old allowlist shape, no longer read)"
        )


def _check_accepted(name: str, entry: object) -> None:
    if not isinstance(entry, dict):
        raise ValueError(
            f"accepted_advisories[{name!r}] must be an object with reason and review_by "
            "(a plain reason string, with no review_by date, is the old allowlist shape, no longer read)"
        )
    if not _reason_ok(entry.get("reason")):
        raise ValueError(f"accepted_advisories[{name!r}] needs a reason")
    review_date(entry.get("review_by"), f"accepted_advisories[{name!r}]")


def load_allowlist_data(data: object) -> dict:
    """Validate allowlist content (the only shape read).

    ``build_only`` keys are exact ``name@version`` with a reason;
    ``accepted_advisories`` entries are
    ``{"reason": ..., "review_by": "YYYY-MM-DD"}``, both required, so an
    acceptance can't sit forever without a re-review. The older shape (a bare
    package name in ``build_only``, a plain reason string for an accepted
    advisory) is refused with a message that says so.
    """
    if not isinstance(data, dict):
        raise ValueError("allowlist must be a JSON object")
    out: dict = {}
    for key in ("build_only", "build_only_roots", "accepted_advisories"):
        section = data.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{key} must map names to reasons")
        for name, entry in section.items():
            if key == "build_only_roots":
                if not _reason_ok(entry):
                    raise ValueError(f"{key}[{name!r}] needs a reason")
            elif key == "build_only":
                _check_build_only(name, entry)
            else:
                _check_accepted(name, entry)
        out[key] = dict(section)
    return out


def load_allowlist(path: Path) -> dict:
    return load_allowlist_data(json.loads(path.read_text(encoding="utf-8")))
