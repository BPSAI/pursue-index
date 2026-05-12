"""Tests for the ingest-approval gate (plan step 4).

The gate refuses `pursue ingest run` until the operator has reviewed
the tranche-diff report and recorded an approval. This module pins
the contract for:

  - is_tranche_approved(log, tranche_sha) → bool
  - record_approval(log, tranche_sha, note, diff_summary, renames)
  - auto_approve_renames(diff) — extracts Class A entries
  - parse_rename_flags(["new=old", ...]) — CLI flag parser
  - append_aliases(aliases_path, rows) — append-only writer

All functions are pure (filesystem-bounded) so tests use tmp_path.
No CLI runner needed — the typer CLI in `ingest_cli.py` is a thin
shell over these primitives.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.ingest import (  # noqa: E402
    append_aliases,
    auto_approve_renames,
    is_tranche_approved,
    parse_rename_flags,
    record_approval,
)


# --- is_tranche_approved ---


def test_gate_refuses_unapproved_tranche(tmp_path: Path) -> None:
    log = tmp_path / "approval-log.jsonl"
    assert is_tranche_approved(log, "abc123") is False


def test_gate_approves_recorded_tranche(tmp_path: Path) -> None:
    log = tmp_path / "approval-log.jsonl"
    record_approval(
        log_path=log,
        tranche_sha="abc123def456",
        note="reviewed and approved",
        diff_summary={"renames_confirmed": 0, "new_content": 0},
        renames_approved=[],
    )
    assert is_tranche_approved(log, "abc123def456") is True


def test_gate_distinguishes_different_tranches(tmp_path: Path) -> None:
    log = tmp_path / "approval-log.jsonl"
    record_approval(log, "abc12345aaaa", "ok", {}, [])
    assert is_tranche_approved(log, "abc12345aaaa") is True
    assert is_tranche_approved(log, "def45678bbbb") is False


def test_gate_handles_missing_log_file(tmp_path: Path) -> None:
    log = tmp_path / "does-not-exist.jsonl"
    assert is_tranche_approved(log, "any") is False


def test_gate_handles_corrupt_rows(tmp_path: Path) -> None:
    """Corrupt rows are skipped, not crash-the-gate. Future-readable JSONL."""
    log = tmp_path / "approval-log.jsonl"
    log.write_text(
        '{"tranche_sha256": "abc12345aaaa"}\n'
        "this is not JSON\n"
        '{"tranche_sha256": "def45678bbbb"}\n'
    )
    assert is_tranche_approved(log, "abc12345aaaa") is True
    assert is_tranche_approved(log, "def45678bbbb") is True


# --- record_approval ---


def test_record_approval_writes_full_row(tmp_path: Path) -> None:
    log = tmp_path / "approval-log.jsonl"
    record_approval(
        log_path=log,
        tranche_sha="65572b38d27c",
        note="reviewed full diff, 16 quarantined approved as renames",
        diff_summary={"renames_confirmed": 0, "quarantined": 16,
                      "restored_unchanged": 1},
        renames_approved=[
            {"old_card_id": "aa11aa11aa11aa11", "new_card_id": "bb22bb22bb22bb22", "method": "operator_manual"},
        ],
    )
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    r = rows[0]
    assert r["tranche_sha256"] == "65572b38d27c"
    assert r["note"] == "reviewed full diff, 16 quarantined approved as renames"
    assert r["approved_by"] == "operator"
    assert "approved_at" in r
    # ISO 8601-ish timestamp.
    assert r["approved_at"].startswith("2026-") or r["approved_at"].startswith("20")
    assert r["diff_summary"]["quarantined"] == 16
    assert len(r["renames_approved"]) == 1


def test_record_approval_appends_not_overwrites(tmp_path: Path) -> None:
    """Each approval is a permanent audit row — never edit, never delete."""
    log = tmp_path / "approval-log.jsonl"
    record_approval(log, "abc", "first", {}, [])
    record_approval(log, "def", "second", {}, [])
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(rows) == 2


# --- auto_approve_renames ---


def test_auto_approve_extracts_class_a_with_byte_collision_method() -> None:
    diff = {
        "renames_confirmed": [
            {"old_card_id": "aa11aa11aa11aa11", "new_card_id": "bb22bb22bb22bb22",
             "byte_sha256": "ff" * 32, "new_title": "X"},
        ],
        "new_content": [],
        "quarantined": [],
    }
    approved = auto_approve_renames(diff)
    assert len(approved) == 1
    assert approved[0]["old_card_id"] == "aa11aa11aa11aa11"
    assert approved[0]["new_card_id"] == "bb22bb22bb22bb22"
    assert approved[0]["method"] == "byte_collision"
    assert approved[0]["byte_sha256"] == "ff" * 32


def test_auto_approve_yields_empty_when_no_class_a() -> None:
    assert auto_approve_renames({"renames_confirmed": []}) == []
    assert auto_approve_renames({}) == []


# --- parse_rename_flags ---


def test_parse_rename_flags_well_formed() -> None:
    rows = parse_rename_flags(["bb22bb22bb22bb22=aa11aa11aa11aa11", "cc33cc33cc33cc33=dd44dd44dd44dd44"])
    assert len(rows) == 2
    assert rows[0]["new_card_id"] == "bb22bb22bb22bb22"
    assert rows[0]["old_card_id"] == "aa11aa11aa11aa11"
    assert rows[0]["method"] == "operator_manual"
    assert rows[1]["new_card_id"] == "cc33cc33cc33cc33"
    assert rows[1]["old_card_id"] == "dd44dd44dd44dd44"


def test_parse_rename_flags_rejects_malformed() -> None:
    """Missing `=`, empty halves, etc. should raise so operator notices."""
    with pytest.raises(ValueError):
        parse_rename_flags(["just-one-id"])
    with pytest.raises(ValueError):
        parse_rename_flags(["=missing-new"])
    with pytest.raises(ValueError):
        parse_rename_flags(["missing-old="])


def test_parse_rename_flags_validates_card_id_format() -> None:
    """Card_ids are 16-char lowercase hex; reject anything else."""
    with pytest.raises(ValueError):
        parse_rename_flags(["INVALID=aa11aa11aa11aa11"])
    with pytest.raises(ValueError):
        parse_rename_flags(["aaaaaaaaaaaaaaaa=NOT_HEX_AT_ALL"])


def test_parse_rename_flags_empty_list() -> None:
    assert parse_rename_flags([]) == []


# --- append_aliases ---


def _aliases_payload(aliases_path: Path) -> dict:
    return json.loads(aliases_path.read_text())


def test_append_aliases_creates_file_if_absent(tmp_path: Path) -> None:
    aliases = tmp_path / "card-aliases.json"
    append_aliases(aliases, [
        {"old_card_id": "aa11aa11aa11aa11", "new_card_id": "bb22bb22bb22bb22", "method": "byte_collision",
         "byte_sha256": "ff" * 32, "established": "2026-05-12T00:00:00Z",
         "tranche_sha256": "65572b38..."},
    ])
    payload = _aliases_payload(aliases)
    assert len(payload["aliases"]) == 1
    assert payload["aliases"][0]["old_card_id"] == "aa11aa11aa11aa11"


def test_append_aliases_appends_to_existing_file(tmp_path: Path) -> None:
    aliases = tmp_path / "card-aliases.json"
    aliases.write_text(json.dumps({"aliases": [
        {"old_card_id": "existing", "new_card_id": "existing_new", "method": "byte_collision"},
    ]}))
    append_aliases(aliases, [
        {"old_card_id": "new", "new_card_id": "new_new", "method": "operator_manual"},
    ])
    payload = _aliases_payload(aliases)
    assert len(payload["aliases"]) == 2
    assert payload["aliases"][0]["old_card_id"] == "existing"  # original preserved
    assert payload["aliases"][1]["old_card_id"] == "new"


def test_append_aliases_no_op_on_empty_list(tmp_path: Path) -> None:
    aliases = tmp_path / "card-aliases.json"
    aliases.write_text(json.dumps({"aliases": []}))
    append_aliases(aliases, [])
    payload = _aliases_payload(aliases)
    assert payload["aliases"] == []
