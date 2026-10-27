"""A ``renames_metadata_only`` row is a rename ``ingest approve`` accepts
on its own (R7C.12) -- no ``--approve-rename`` flag -- with its own alias
method, and every downstream reader of alias methods knows that method.

  * ``auto_approve_renames`` emits ``method: "metadata-only-resave"``;
  * ``pursue ingest approve`` materializes it in ``card-aliases.json``;
  * the pre-approval TOCTOU audit re-fetches its new bytes and BLOCKS on a
    mismatch (the byte evidence is about exactly those bytes);
  * the release shrink guard lets the alias excuse its removed old id;
  * the ingest worklist scopes its new side for OCR like any rename.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.ingest import auto_approve_renames
from pursue_index.ingest_scope import REASON_RENAMED, scope_pdf_img_cards
from pursue_index.post_ingest_audit import (
    audit_targets,
    collect_audit_targets,
    has_blocking_mismatch,
)
from pursue_index.release.alias_exemption import ALLOWED_ALIAS_METHODS
from pursue_index.tranche_resave import RESAVE_BUCKET, RESAVE_METHOD

_SHA = "096ef2c0058a" + "0" * 52
OLD_ID, NEW_ID = "a0f6663169c21caf", "ff3939f95d878062"
NEW_URL = "https://x/DOW-UAP-D042.pdf"
NEW_BYTES_SHA = "ca" * 32
OLD_BYTES_SHA = "d5" * 32


def _diff() -> dict:
    row = {"old_card_id": OLD_ID, "new_card_id": NEW_ID, "byte_sha256": NEW_BYTES_SHA,
           "old_byte_sha256": OLD_BYTES_SHA, "verdict": "metadata-only", "method": RESAVE_METHOD,
           "new_title": "DOW-UAP-D042", "new_asset_filename": "DOW-UAP-D042.pdf",
           "new_asset_url": NEW_URL}
    return {"tranche_sha256": _SHA,
            "summary": {"renames_confirmed": 0, "new_content": 0, "quarantined": 0,
                        RESAVE_BUCKET: 1},
            "renames_confirmed": [], "new_content": [], "quarantined": [],
            RESAVE_BUCKET: [row], "restored_unchanged": [], "restored_modified": [],
            "removed": [], "field_only_changes": []}


def test_auto_approve_emits_metadata_only_resave_method() -> None:
    assert auto_approve_renames(_diff(), metadata_resaves=True) == [{
        "old_card_id": OLD_ID, "new_card_id": NEW_ID,
        "byte_sha256": NEW_BYTES_SHA, "method": "metadata-only-resave",
        "old_byte_sha256": OLD_BYTES_SHA, "new_byte_sha256": NEW_BYTES_SHA,
        "change_nature": "metadata-only",
    }]


def test_auto_approve_omits_byte_evidence_it_does_not_have() -> None:
    diff = _diff()
    for key in ("old_byte_sha256", "verdict"):
        diff[RESAVE_BUCKET][0].pop(key)
    [alias] = auto_approve_renames(diff, metadata_resaves=True)
    assert "old_byte_sha256" not in alias and "change_nature" not in alias
    assert alias["new_byte_sha256"] == NEW_BYTES_SHA


def test_byte_collision_rows_carry_no_change_nature() -> None:
    diff = _diff()
    diff["renames_confirmed"] = [{"old_card_id": "1" * 16, "new_card_id": "2" * 16,
                                  "byte_sha256": "ab" * 32}]
    collision = auto_approve_renames(diff)[0]
    assert collision["method"] == "byte_collision"
    assert not {"old_byte_sha256", "new_byte_sha256", "change_nature"} & set(collision)


def test_approve_materializes_alias_without_approve_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    monkeypatch.setattr(settings, "ingest_auto_approve_metadata_resaves", True)  # opted in
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir()
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps(_diff()))
    result = CliRunner().invoke(app, [
        "ingest", "approve", "--tranche", _SHA, "--note", "D042 re-save", "--skip-audit",
        "--log", str(tmp_path / "log.jsonl"), "--aliases", str(tmp_path / "aliases.json"),
        "--diff-dir", str(diff_dir), "--snapshots-dir", str(tmp_path / "snaps"),
    ])
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert (alias["old_card_id"], alias["new_card_id"]) == (OLD_ID, NEW_ID)
    assert alias["method"] == "metadata-only-resave"
    assert alias["tranche_sha256"] == _SHA
    assert alias["byte_sha256"] == NEW_BYTES_SHA  # the TOCTOU audit's contract
    assert alias["old_byte_sha256"] == OLD_BYTES_SHA
    assert alias["new_byte_sha256"] == NEW_BYTES_SHA
    assert alias["change_nature"] == "metadata-only"
    logged = json.loads((tmp_path / "log.jsonl").read_text())["renames_approved"]
    assert [r["method"] for r in logged] == ["metadata-only-resave"]
    assert "metadata-only re-save" in result.output
    assert "not addressed" not in result.output


def test_audit_blocks_when_resaved_bytes_moved_since_the_diff() -> None:
    aliases = auto_approve_renames(_diff(), metadata_resaves=True)
    manifest = {"cards": [{"card_id": NEW_ID, "asset_url": NEW_URL}]}
    [target] = collect_audit_targets(aliases, _diff(), manifest)
    assert target["expected_sha"] == NEW_BYTES_SHA
    assert not has_blocking_mismatch(audit_targets([target], {NEW_URL: NEW_BYTES_SHA}.get))
    assert has_blocking_mismatch(audit_targets([target], {NEW_URL: "ee" * 32}.get))


def test_shrink_guard_accepts_the_method() -> None:
    assert RESAVE_METHOD in ALLOWED_ALIAS_METHODS


def test_worklist_scopes_the_new_side_as_renamed() -> None:
    scoped = scope_pdf_img_cards(_diff(), _SHA)
    assert [(s.card_id, s.reason) for s in scoped] == [(NEW_ID, REASON_RENAMED)]
