"""Superseding a sidecar: the new pass in front, the old one kept.

Split from ``redescribe``. ``supersede_sidecar`` builds the result, ``dry_supersede``
rehearses it with placeholder pages, and ``write_atomic`` lands it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.sidecar import DEFAULT_CONTEXT, validate_sidecar

METHOD = "vision-run"


def supersede_sidecar(
    existing: dict[str, Any], new_pages: list[dict[str, Any]], *,
    model: str, now: str,
) -> dict[str, Any]:
    """``existing`` with a new pass in front and the old one kept, not dropped.

    Key order is preserved (the new values take the old keys' places), so the
    diff of a re-described file is the pass, the pages and one new key.
    """
    old_pass = existing.get("our_pass") or {}
    superseded = list(existing.get("superseded_passes") or [])
    superseded.append({
        "our_pass": old_pass, "pages": existing.get("pages", []), "superseded_at": now,
    })
    new = dict(existing)
    new["our_pass"] = {
        "model": model, "method": METHOD,
        "context": DEFAULT_CONTEXT, "described_at": now,
    }
    new["pages"] = new_pages
    new["superseded_passes"] = superseded
    validate_sidecar(new)
    return new


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def dry_supersede(
    existing: dict[str, Any], card_items: list[EligibleItem], model: str
) -> str | None:
    """Why ``existing`` (just re-read) could not be superseded, or None.

    Validates it and runs the real ``supersede_sidecar`` on placeholder pages,
    so a sidecar that went bad since planning is refused before the card's
    first paid call, not after its last.
    """
    try:
        validate_sidecar(existing)
        placeholders = [
            {"page": i.page, "row_key": i.row_key, "observations": [{"claim": "placeholder"}]}
            for i in card_items
        ]
        supersede_sidecar(existing, placeholders, model=model, now="dry-run")
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


