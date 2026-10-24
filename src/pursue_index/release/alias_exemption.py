"""Which alias rows may excuse a removed ``card_id`` from the shrink guard.

An alias row in ``data/card-aliases.json`` says "old id -> new id". The
shrink guard treats a removed id as an approved rename only when the row
is something an operator actually signed off on:

* its ``method`` is on :data:`ALLOWED_ALIAS_METHODS`, and
* its ``tranche_sha256`` appears in ``data/tranche-approval-log.jsonl``.

Every exemption that is applied is written to the audit log, so a rename
that quietly drops a card leaves a row naming the old id, the new id, the
method and the tranche.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pursue_index.ingest_scope import load_aliases

__all__ = [
    "ALLOWED_ALIAS_METHODS",
    "AliasExemption",
    "add_exemption_args",
    "approved_tranche_shas",
    "resolve_with_audit",
    "trusted_alias_map",
]

# Methods present in data/card-aliases.json plus the revoke tombstone.
ALLOWED_ALIAS_METHODS = frozenset({"operator_manual", "operator_revoke"})
_REVOKE = "operator_revoke"


@dataclass(frozen=True)
class AliasExemption:
    old_id: str
    new_id: str
    method: str
    tranche_sha256: str


def add_exemption_args(
    parser: argparse.ArgumentParser, *, approval_log: Path, audit_log: Path
) -> None:
    """``--approval-log`` / ``--audit-log`` shared by both builders."""
    parser.add_argument(
        "--approval-log", type=Path, default=approval_log,
        help="tranche-approval-log.jsonl; an alias row only excuses a removed "
        "id when its tranche is recorded here.",
    )
    parser.add_argument(
        "--audit-log", type=Path, default=audit_log,
        help="Where shrink exceptions and alias exemptions are recorded.",
    )


def approved_tranche_shas(approval_log: Path | None) -> set[str]:
    """Full tranche shas recorded in the approval log; empty if absent."""
    if approval_log is None or not approval_log.is_file():
        return set()
    out: set[str] = set()
    for line in approval_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            sha = json.loads(line).get("tranche_sha256")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(sha, str) and sha:
            out.add(sha)
    return out


def trusted_alias_map(
    aliases_path: Path | None, approval_log: Path | None
) -> dict[str, AliasExemption]:
    """``old_id -> AliasExemption`` for rows that may excuse a shrink.

    Later rows win per old id; a ``operator_revoke`` row removes the
    mapping. Rows with an unlisted method, or a tranche the approval log
    does not contain, are ignored outright (they neither exempt nor
    override an earlier trusted row).
    """
    if aliases_path is None:
        return {}
    approved = approved_tranche_shas(approval_log)
    out: dict[str, AliasExemption] = {}
    for row in load_aliases(aliases_path):
        old_id, new_id = row.get("old_card_id"), row.get("new_card_id")
        method = str(row.get("method") or "")
        tranche = str(row.get("tranche_sha256") or row.get("tranche") or "")
        if not (old_id and new_id) or method not in ALLOWED_ALIAS_METHODS:
            continue
        if tranche not in approved:
            continue
        if method == _REVOKE:
            out.pop(old_id, None)
            continue
        out[old_id] = AliasExemption(old_id, new_id, method, tranche)
    return out


def _record(script: str, ex: AliasExemption, audit_log: Path) -> None:
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "event": "alias_shrink_exemption",
        "script": script,
        "old_card_id": ex.old_id,
        "new_card_id": ex.new_id,
        "method": ex.method,
        "tranche_sha256": ex.tranche_sha256,
        "at": datetime.now(UTC).isoformat(),
    }
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def resolve_with_audit(
    script: str,
    shrunk: list[str],
    rebuilt: set[str],
    aliases_path: Path | None,
    approval_log: Path | None,
    audit_log: Path,
) -> tuple[list[str], list[str]]:
    """Split ``shrunk`` into ``(renamed, missing)``, auditing each exemption."""
    trusted = trusted_alias_map(aliases_path, approval_log)
    renamed: list[str] = []
    missing: list[str] = []
    for old_id in shrunk:
        ex = trusted.get(old_id)
        if ex is not None and ex.new_id in rebuilt:
            _record(script, ex, audit_log)
            renamed.append(f"{old_id} -> {ex.new_id}")
        else:
            missing.append(old_id)
    return renamed, missing
