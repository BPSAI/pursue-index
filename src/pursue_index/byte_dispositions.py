"""Byte-change dispositions: an append-only record of reviewed upstream re-saves.

``data/byte-change-dispositions.jsonl`` holds one row per reviewed byte change
on a card. The row is the provenance re-stamp: run artifacts such as
``meta.json`` are never edited, so a card whose OCR read the old bytes stays
explained by a row here instead.

Row fields (all required, no others)::

    card_id, old_sha256 (the bytes the OCR read), new_sha256 (the registry's
    latest), disposition, reviewed_at (ISO date), evidence (short public note),
    evidence_ref (sha256 of the evidence report's UTF-8 bytes, lowercase hex),
    ocr_from (sha256 of the bytes the OCR read; must equal old_sha256 for
    ``resave-content-verified``, and ``covers`` checks it again)

The file is public, so ``evidence`` and ``evidence_ref`` must not name a
repository, a URL or an issue reference.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.card_id import InvalidCardIdError, require_card_id

DISPOSITIONS_FILENAME = "byte-change-dispositions.jsonl"
RESAVE_CONTENT_VERIFIED = "resave-content-verified"
CONTENT_CHANGED = "content-changed"
_DISPOSITIONS = {RESAVE_CONTENT_VERIFIED, CONTENT_CHANGED}
_FIELDS = {
    "card_id", "old_sha256", "new_sha256", "disposition", "reviewed_at",
    "evidence", "evidence_ref", "ocr_from",
}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PRIVATE_REFERENCE = re.compile(
    r"https?:|www\.|://|#\d+|\bpursue-[a-z]+|\bbpsai\b|github", re.IGNORECASE
)


class ByteDispositionError(ValueError):
    """The dispositions file is malformed; callers must not guess past it."""


@dataclass(frozen=True)
class Disposition:
    card_id: str
    old_sha256: str
    new_sha256: str
    disposition: str
    reviewed_at: str
    evidence: str
    evidence_ref: str
    ocr_from: str


def _hex(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{name} must be 64 lowercase hex characters")
    return value


def _parse(row: Any) -> Disposition:
    if not isinstance(row, dict):
        raise ValueError("row is not a JSON object")
    missing = _FIELDS - row.keys()
    if missing:
        raise ValueError(f"missing field(s): {sorted(missing)}")
    extra = row.keys() - _FIELDS
    if extra:
        raise ValueError(f"unknown field(s): {sorted(extra)}")
    try:
        card_id = require_card_id(row["card_id"])
    except InvalidCardIdError as exc:
        raise ValueError(str(exc)) from exc
    kind = row["disposition"]
    if kind not in _DISPOSITIONS:
        raise ValueError(f"unknown disposition {kind!r}")
    old, new = _hex(row["old_sha256"], "old_sha256"), _hex(row["new_sha256"], "new_sha256")
    ref = _hex(row["evidence_ref"], "evidence_ref")
    try:
        date.fromisoformat(row["reviewed_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("reviewed_at must be an ISO date") from exc
    evidence = row["evidence"]
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("evidence must be a non-empty string")
    if _PRIVATE_REFERENCE.search(evidence):
        raise ValueError("evidence names a repository, URL or issue reference")
    ocr_from = _hex(row["ocr_from"], "ocr_from")
    if kind == RESAVE_CONTENT_VERIFIED and ocr_from != old:
        raise ValueError("ocr_from must equal old_sha256 for resave-content-verified")
    return Disposition(card_id, old, new, kind, row["reviewed_at"], evidence, ref, ocr_from)


def load_byte_change_dispositions(path: Path) -> dict[tuple[str, str], Disposition]:
    """``(card_id, new_sha256) -> Disposition``. An absent file is no dispositions."""
    out: dict[tuple[str, str], Disposition] = {}
    if not path.exists():
        return out
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            disp = _parse(json.loads(line))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ByteDispositionError(f"{path}:{lineno}: {exc}") from exc
        key = (disp.card_id, disp.new_sha256)
        if key in out:
            raise ByteDispositionError(f"{path}:{lineno}: duplicate (card_id, new_sha256) {key}")
        out[key] = disp
    return out


def covers(
    dispositions: dict[tuple[str, str], Disposition], card_id: str, ocr_sha: str, registry_sha: str
) -> bool:
    """True when a ``resave-content-verified`` row covers exactly this pair of shas.

    ``ocr_sha`` is the card's actual OCR ``pdf_sha256``; the row's ``ocr_from`` must
    equal it (the loader's ``ocr_from == old_sha256`` check compares the row with
    itself, so this is the check that ties the row to the real OCR input)."""
    disp = dispositions.get((card_id, registry_sha))
    return (
        disp is not None
        and disp.disposition == RESAVE_CONTENT_VERIFIED
        and disp.old_sha256 == ocr_sha
        and disp.ocr_from == ocr_sha  # the OCR's actual pdf_sha256, not the row's own field
    )
