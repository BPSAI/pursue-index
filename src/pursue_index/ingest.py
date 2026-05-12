"""Ingest-approval gate (plan step 4).

The ingest stage is the FIRST point in the pipeline where upstream
catalog changes propagate into the deployed corpus state (manifest
promotion → OCR → embed → deploy rebuild → aliases written into
data/card-aliases.json). Everything before ingest — poll, byte-archive,
tranche-diff — is always-on and unattended-safe. Ingest itself is
gated on operator approval because, by design, this is where an
inadequately-reviewed tranche could ship 16 silent aliases or
incorporate tampered content into the public manifest.

This module owns the primitives that gate enforces:

  * is_tranche_approved(log, sha) — the boolean the orchestrator queries
  * record_approval(log, sha, note, summary, renames) — the audit row
  * auto_approve_renames(diff) — extracts Class A entries (byte-sha
    collision, cryptographically safe) so they need no explicit operator
    flag; operator approval of the tranche implicitly accepts them
  * parse_rename_flags(["new=old", ...]) — converts the CLI's
    --approve-rename operator_manual flags into alias-row dicts
  * append_aliases(path, rows) — append-only writer for the
    deployment-side aliases file the worker reads

The CLI surface lives in `pursue_index.cli.ingest_cli`.

Failure-mode discipline:

  * Approval log is append-only; corrupt rows skipped, never crash gate.
  * Card_id validation rejects malformed CLI input early — better to
    refuse the approval than to write an unreachable alias row.
  * `--approve-rename` always carries `method: "operator_manual"` —
    distinct from `byte_collision` so audit trails can distinguish
    operator-judgment renames from cryptographically-confirmed ones.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CARD_ID_RE = re.compile(r"^[a-f0-9]{16}$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_log_rows(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # Skip corrupt rows; the gate must never wedge on a single
            # malformed entry. Audit-trail readers can grep for them.
            continue
    return rows


def _shas_match(stored: str, query: str) -> bool:
    """Match stored sha against query sha allowing prefix on either side.

    Approval log stores the full csv_sha256; CLI may be invoked with
    the 12-char display prefix or the full sha. Either should match
    the other as long as one is a prefix of the other and at least
    8 chars overlap (avoid empty-string false matches).
    """
    if not stored or not query:
        return False
    shorter, longer = (query, stored) if len(query) <= len(stored) else (stored, query)
    if len(shorter) < 8:
        return False
    return longer.startswith(shorter)


def is_tranche_approved(log_path: Path, tranche_sha: str) -> bool:
    """Return True iff there is at least one approval row for this sha
    (full or prefix match in either direction)."""
    for row in _read_log_rows(log_path):
        if _shas_match(row.get("tranche_sha256", ""), tranche_sha):
            return True
    return False


def record_approval(
    log_path: Path,
    tranche_sha: str,
    note: str,
    diff_summary: dict[str, int],
    renames_approved: list[dict[str, Any]],
) -> None:
    """Append one approval row to the append-only log."""
    row = {
        "tranche_sha256": tranche_sha,
        "approved_at": _now_iso(),
        "approved_by": "operator",
        "note": note,
        "diff_summary": diff_summary,
        "renames_approved": renames_approved,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def auto_approve_renames(diff: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract Class A entries from a tranche-diff into alias-row shape.

    These are renames where the new card's byte_sha256 collides with
    an existing registry entry — cryptographically confirmed safe
    aliases. Operator approval of the tranche implicitly accepts them
    (no explicit per-card flag needed).
    """
    out: list[dict[str, Any]] = []
    for r in diff.get("renames_confirmed", []) or []:
        out.append({
            "old_card_id": r["old_card_id"],
            "new_card_id": r["new_card_id"],
            "byte_sha256": r.get("byte_sha256"),
            "method": "byte_collision",
        })
    return out


def parse_rename_flags(flags: list[str]) -> list[dict[str, Any]]:
    """Parse repeatable --approve-rename `<new_id>=<old_id>` flags.

    Each flag becomes an alias row with `method: "operator_manual"`.
    Raises ValueError on malformed input (better to refuse than to
    write an unreachable alias).
    """
    out: list[dict[str, Any]] = []
    for raw in flags:
        if "=" not in raw:
            raise ValueError(
                f"--approve-rename expects <new_id>=<old_id>, got: {raw!r}"
            )
        new_id, _, old_id = raw.partition("=")
        new_id = new_id.strip()
        old_id = old_id.strip()
        if not new_id or not old_id:
            raise ValueError(
                f"--approve-rename halves must both be non-empty, got: {raw!r}"
            )
        if not _CARD_ID_RE.match(new_id):
            raise ValueError(
                f"--approve-rename new_id must be 16-char lowercase hex, got: {new_id!r}"
            )
        if not _CARD_ID_RE.match(old_id):
            raise ValueError(
                f"--approve-rename old_id must be 16-char lowercase hex, got: {old_id!r}"
            )
        out.append({
            "old_card_id": old_id,
            "new_card_id": new_id,
            "method": "operator_manual",
        })
    return out


def append_aliases(aliases_path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rows to data/card-aliases.json's `aliases` list.

    File schema is `{"aliases": [...]}`. We read the existing payload,
    extend the list, and write back. Atomic-ish: read once, write
    once. For the corpus-scale we're targeting (low hundreds of
    aliases lifetime) this is fine; if it grows, switch to JSONL.
    """
    if not rows:
        return
    aliases_path.parent.mkdir(parents=True, exist_ok=True)
    if aliases_path.exists():
        payload = json.loads(aliases_path.read_text())
    else:
        payload = {"aliases": []}
    payload.setdefault("aliases", []).extend(rows)
    aliases_path.write_text(json.dumps(payload, indent=2) + "\n")
