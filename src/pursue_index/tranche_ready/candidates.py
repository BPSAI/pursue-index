"""Rename/quarantine candidates for the tranche-ready record (``$defs/candidate``).

One candidate per tranche-diff row that needs a ruling: Class A renames
(``renames_confirmed``) and opted-in metadata-only re-saves
(``tranche_resave.RESAVE_BUCKET``) are ``rename-candidate``; Class C rows
(``quarantined``) are ``quarantine``. The matched old card is the row's own
``old_card_id``, else the card its ``resave_evidence`` names, else its
strongest title-continuity match.

The verdict is ``tranche_bytes.classify_bytes`` over the two staged files
(``old_bytes``), each re-verified against its sha by the classifier's
worker. Byte-identical sides are a rename with nothing changed --
``metadata-only`` with zero appended bytes, no classifier run. A missing
side nulls the verdict; ``byte_verdict_reason`` says which, and the
candidate forces stop-and-ask, as does a ``content-changed`` quarantine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pursue_index.tranche_bytes import METADATA_ONLY, classify_bytes
from pursue_index.tranche_ready.old_bytes import StagedBytes
from pursue_index.tranche_resave import EVIDENCE_KEY, RESAVE_BUCKET

__all__ = ["CandidateRow", "build_candidate", "candidate_rows"]

RENAME, QUARANTINE = "rename-candidate", "quarantine"
_RESAVE_RENAME = "approve-rename-metadata-only-resave"
_RENAME = "approve-rename"
_OPERATOR = "operator-rule-required"


@dataclass(frozen=True)
class CandidateRow:
    """A diff row that needs a ruling, with the old card it is matched to."""

    kind: str
    new_card_id: str
    old_card_id: str | None
    row: dict[str, Any]


def _quarantine_old_id(row: dict[str, Any]) -> str | None:
    evidence = row.get(EVIDENCE_KEY) or {}
    if evidence.get("old_card_id"):
        return evidence["old_card_id"]
    matched = row.get("matched_against") or []
    return matched[0] if matched else None


def candidate_rows(diff: dict[str, Any]) -> list[CandidateRow]:
    """Renames, then moved re-saves, then quarantines, each in diff order."""
    out = [CandidateRow(RENAME, r["new_card_id"], r.get("old_card_id"), r)
           for key in ("renames_confirmed", RESAVE_BUCKET) for r in diff.get(key) or []]
    out += [CandidateRow(QUARANTINE, r["new_card_id"], _quarantine_old_id(r), r)
            for r in diff.get("quarantined") or []]
    return out


def _signals(c: CandidateRow) -> list[str] | None:
    if "continuity_reasons" in c.row:
        return list(c.row["continuity_reasons"])
    for match in c.row.get("matches") or []:
        if match.get("card_id") == c.old_card_id:
            return list(match.get("reasons") or [])
    return None


def _verdict(old: StagedBytes, new: StagedBytes, classify: Callable[..., str]) -> str | None:
    if old.path is None or new.path is None:
        return None
    if old.sha256 == new.sha256:
        return METADATA_ONLY
    return classify(old.path, new.path, old_sha256=old.sha256, new_sha256=new.sha256)


def _evidence(old: StagedBytes, new: StagedBytes, verdict: str) -> dict[str, Any]:
    old_data, new_data = Path(old.path).read_bytes(), Path(new.path).read_bytes()
    prefix = new_data.startswith(old_data)
    out: dict[str, Any] = {"old_prefix_of_new": prefix}
    if prefix:
        appended = len(new_data) - len(old_data)
        out["appended_bytes"] = appended
        out["incremental_update"] = verdict == METADATA_ONLY and appended > 0
    return out


def _disposition(kind: str, verdict: str | None, identical: bool) -> tuple[bool, str]:
    """``(stop_and_ask, recommended_disposition)``."""
    if verdict == METADATA_ONLY:
        return False, _RENAME if identical else _RESAVE_RENAME
    if verdict is not None and kind == RENAME:
        return False, _RENAME
    return True, _OPERATOR


def build_candidate(
    c: CandidateRow,
    *,
    old_title: str | None,
    old_side: StagedBytes,
    new_side: StagedBytes,
    classify: Callable[..., str] = classify_bytes,
) -> dict[str, Any]:
    """The schema's candidate object for ``c`` given both staged sides."""
    verdict = _verdict(old_side, new_side, classify)
    identical = verdict is not None and old_side.sha256 == new_side.sha256
    stop, disposition = _disposition(c.kind, verdict, identical)
    old_ok = old_side.failure is None
    out: dict[str, Any] = {"kind": c.kind, "new_card_id": c.new_card_id,
                           "old_card_id": c.old_card_id}
    for key, value in (("new_title", c.row.get("new_title")), ("old_title", old_title),
                       ("continuity_signals", _signals(c))):
        if value is not None:
            out[key] = value
    out.update(
        old_byte_sha256=old_side.sha256 if old_ok else None,
        new_byte_sha256=new_side.sha256,
        old_byte_size=old_side.size if old_ok else None,
        new_byte_size=new_side.size,
        byte_verdict=verdict,
        byte_verdict_reason=None if verdict else (new_side.failure or old_side.failure),
        evidence=_evidence(old_side, new_side, verdict) if verdict else None,
        stop_and_ask=stop,
        recommended_disposition=disposition,
    )
    return out
