"""With ``ingest_auto_approve_metadata_resaves`` off a metadata-only verdict is
evidence only: quarantine, ``removed`` and the worklist scope are exactly what
an unclassified rename would give, and an operator-approved rename carries the
evidence onto its alias row."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.ingest_scope import (
    REASON_QUARANTINED_NEW,
    REASON_RENAMED,
    scope_pdf_img_cards,
)
from pursue_index.tranche_resave import EVIDENCE_KEY, RESAVE_BUCKET
from tests.unit.test_ingest_resave_approve import _SHA, NEW_BYTES_SHA, NEW_ID, OLD_BYTES_SHA, OLD_ID
from tests.unit.test_ingest_resave_approve import _diff as resave_bucket_diff
from tests.unit.test_tranche_diff_resave import _diff, _pair, _sha

KEY = "ingest_auto_approve_metadata_resaves"
EVIDENCE = {"old_card_id": OLD_ID, "old_byte_sha256": OLD_BYTES_SHA,
            "new_byte_sha256": NEW_BYTES_SHA, "change_nature": "metadata-only",
            "classifier": "pdf-update-parser/pypdf9/abc", "crosscheck": ["content-streams", "text"]}
URL = "https://x/DOW-UAP-D042.pdf"


def _held_diff() -> dict:
    row = {"new_card_id": NEW_ID, "new_byte_sha256": NEW_BYTES_SHA, "matched_against": [OLD_ID],
           "new_asset_filename": "DOW-UAP-D042.pdf", "new_asset_url": URL, "asset_type": "PDF",
           EVIDENCE_KEY: EVIDENCE}
    return {"tranche_sha256": _SHA, "summary": {"quarantined": 1},
            "renames_confirmed": [], "new_content": [], "quarantined": [row],
            "restored_unchanged": [], "restored_modified": [], "removed": [],
            "field_only_changes": []}


def test_off_keeps_the_row_quarantined_with_evidence_and_the_old_card_removed(tmp_path) -> None:
    old, new = _pair()
    diff = _diff(old, new, tmp_path, {_sha(old): old, _sha(new): new}, move=False)
    assert RESAVE_BUCKET not in diff and RESAVE_BUCKET not in diff["summary"]
    [row] = diff["quarantined"]
    evidence = row[EVIDENCE_KEY]
    assert (evidence["old_card_id"], evidence["change_nature"]) == (OLD_ID, "metadata-only")
    assert (evidence["old_byte_sha256"], evidence["new_byte_sha256"]) == (_sha(old), _sha(new))
    assert evidence["classifier"] and evidence["crosscheck"]
    assert [r["card_id"] for r in diff["removed"]] == [OLD_ID]
    assert diff["summary"]["quarantined"] == 1 and diff["summary"]["removed"] == 1


def test_on_moves_the_row_and_drops_the_old_card_from_removed(tmp_path) -> None:
    old, new = _pair()
    diff = _diff(old, new, tmp_path, {_sha(old): old, _sha(new): new}, move=True)
    assert diff["quarantined"] == [] and len(diff[RESAVE_BUCKET]) == 1
    assert diff["removed"] == []


def test_scope_off_treats_the_held_row_like_any_quarantine() -> None:
    scoped = scope_pdf_img_cards(_held_diff(), _SHA)
    assert [(s.card_id, s.reason) for s in scoped] == [(NEW_ID, REASON_QUARANTINED_NEW)]


def test_scope_on_without_an_established_alias_excludes_the_resave_row() -> None:
    assert scope_pdf_img_cards(resave_bucket_diff(), _SHA) == []


def test_scope_on_with_the_auto_alias_includes_it_as_renamed() -> None:
    alias = {"old_card_id": OLD_ID, "new_card_id": NEW_ID, "tranche_sha256": _SHA,
             "method": "metadata-only-resave"}
    scoped = scope_pdf_img_cards(resave_bucket_diff(), _SHA, aliases=[alias])
    assert [(s.card_id, s.reason) for s in scoped] == [(NEW_ID, REASON_RENAMED)]


def test_scope_with_an_operator_alias_for_a_held_row_is_renamed() -> None:
    alias = {"old_card_id": OLD_ID, "new_card_id": NEW_ID, "tranche_sha256": _SHA,
             "method": "operator_manual"}
    scoped = scope_pdf_img_cards(_held_diff(), _SHA, aliases=[alias])
    assert [(s.card_id, s.reason) for s in scoped] == [(NEW_ID, REASON_RENAMED)]


def _approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str):
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    monkeypatch.setattr(settings, KEY, False, raising=False)
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir(exist_ok=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps(_held_diff()))
    return CliRunner().invoke(app, [
        "ingest", "approve", "--tranche", _SHA, "--note", "n", "--skip-audit",
        "--log", str(tmp_path / "log.jsonl"), "--aliases", str(tmp_path / "aliases.json"),
        "--diff-dir", str(diff_dir), "--snapshots-dir", str(tmp_path / "snaps"), *extra,
    ])


def test_default_approve_prints_the_held_line_and_writes_no_alias(tmp_path, monkeypatch) -> None:
    result = _approve(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert f"held: metadata-only re-save {NEW_ID}={OLD_ID}" in result.output
    assert not (tmp_path / "aliases.json").exists()
    assert "not addressed" in result.output  # the held row counts as unaddressed


def test_operator_approval_of_a_held_row_records_the_evidence(tmp_path, monkeypatch) -> None:
    result = _approve(tmp_path, monkeypatch, "--approve-rename", f"{NEW_ID}={OLD_ID}")
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["method"] == "operator_manual"
    assert alias["old_byte_sha256"] == OLD_BYTES_SHA
    assert alias["new_byte_sha256"] == NEW_BYTES_SHA
    assert alias["change_nature"] == "metadata-only"
    assert alias["classifier"] == EVIDENCE["classifier"]
    assert alias["crosscheck"] == EVIDENCE["crosscheck"]
