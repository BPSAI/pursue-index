"""The unattended metadata-only re-save auto-approval is opt-in (default off).

Off: the verdict stays in the diff and audit row, but the rename is not
aliased -- it waits for the operator (``--approve-rename new=old``).
On: the behavior the R7C.12/R7C.14 tests pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from pursue_index.config import settings
from pursue_index.config.settings import Settings
from pursue_index.ingest import auto_approve_renames
from pursue_index.tranche_resave import RESAVE_BUCKET
from tests.unit.test_ingest_resave_approve import _SHA, NEW_ID, OLD_ID, _diff

KEY = "ingest_auto_approve_metadata_resaves"


def _collision_diff() -> dict:
    diff = _diff()
    diff["renames_confirmed"] = [{"old_card_id": "1" * 16, "new_card_id": "2" * 16,
                                  "byte_sha256": "ab" * 32}]
    return diff


def test_the_setting_defaults_to_off() -> None:
    assert Settings.model_fields[KEY].default is False


def test_default_leaves_resave_rows_out_but_keeps_byte_collisions() -> None:
    rows = auto_approve_renames(_collision_diff())
    assert [r["method"] for r in rows] == ["byte_collision"]


def test_opted_in_emits_the_resave_alias_too() -> None:
    rows = auto_approve_renames(_collision_diff(), metadata_resaves=True)
    assert [r["method"] for r in rows] == ["byte_collision", "metadata-only-resave"]


def _approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str):
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir(exist_ok=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps(_diff()))
    return CliRunner().invoke(app, [
        "ingest", "approve", "--tranche", _SHA, "--note", "n", "--skip-audit",
        "--log", str(tmp_path / "log.jsonl"), "--aliases", str(tmp_path / "aliases.json"),
        "--diff-dir", str(diff_dir), "--snapshots-dir", str(tmp_path / "snaps"), *extra,
    ])


def test_default_approve_keeps_the_resave_quarantined_and_says_so(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, KEY, False, raising=False)
    result = _approve(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "aliases.json").exists()
    assert "1 metadata-only re-save rename(s) held" in result.output
    assert f"--approve-rename {NEW_ID}={OLD_ID}" in result.output


def test_operator_can_still_approve_a_held_resave_by_hand(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, KEY, False, raising=False)
    result = _approve(tmp_path, monkeypatch, "--approve-rename", f"{NEW_ID}={OLD_ID}")
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["method"] == "operator_manual"


def test_opted_in_approve_materializes_the_resave_alias(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, KEY, True, raising=False)
    result = _approve(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["method"] == "metadata-only-resave"


def test_the_diff_still_records_the_verdict_when_off() -> None:
    assert _diff()[RESAVE_BUCKET][0]["verdict"] == "metadata-only"
