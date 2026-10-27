"""``ingest approve`` never silently drops re-save rows the diff already moved.

A diff generated with auto-approval ON has moved its re-save rows out of
quarantine; approving it with the setting now OFF would record nothing for
them, so it refuses and names the way out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from pursue_index.config import settings
from tests.unit.test_ingest_resave_approve import _SHA, NEW_BYTES_SHA, NEW_ID, OLD_ID
from tests.unit.test_ingest_resave_approve import _diff as bucket_diff
from tests.unit.test_tranche_diff_resave import _diff as tranche_diff_of
from tests.unit.test_tranche_diff_resave import _pair, _sha

KEY = "ingest_auto_approve_metadata_resaves"


def _approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diff: dict, *, setting: bool,
             extra: tuple[str, ...] = ()):
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    monkeypatch.setattr(settings, KEY, setting, raising=False)
    diff_dir = tmp_path / "diffs"
    diff_dir.mkdir(exist_ok=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps(diff))
    return CliRunner().invoke(app, [
        "ingest", "approve", "--tranche", _SHA, "--note", "n", "--skip-audit",
        "--log", str(tmp_path / "log.jsonl"), "--aliases", str(tmp_path / "aliases.json"),
        "--diff-dir", str(diff_dir), "--snapshots-dir", str(tmp_path / "snaps"), *extra,
    ])


def _on_diff() -> dict:
    return {**bucket_diff(), "auto_approve_metadata_resaves": True}


def test_diff_records_the_setting_it_was_generated_with(tmp_path) -> None:
    old, new = _pair()
    files = {_sha(old): old, _sha(new): new}
    assert tranche_diff_of(old, new, tmp_path, files, move=True)["auto_approve_metadata_resaves"] is True
    off = tranche_diff_of(old, new, tmp_path, files, move=False)
    assert off.get("auto_approve_metadata_resaves", False) is False  # absent == off (legacy)


def test_on_diff_off_setting_refuses_and_names_the_rows(tmp_path, monkeypatch) -> None:
    result = _approve(tmp_path, monkeypatch, _on_diff(), setting=False)
    assert result.exit_code == 2, result.output
    assert f"{NEW_ID}={OLD_ID}" in result.output
    assert "re-run" in result.output.lower() and "--approve-rename" in result.output
    assert not (tmp_path / "aliases.json").exists()
    assert not (tmp_path / "log.jsonl").exists()


def test_explicit_approve_rename_is_the_way_out_and_records_the_evidence(
    tmp_path, monkeypatch,
) -> None:
    result = _approve(tmp_path, monkeypatch, _on_diff(), setting=False,
                      extra=("--approve-rename", f"{NEW_ID}={OLD_ID}"))
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["method"] == "operator_manual"
    assert (alias["change_nature"], alias["new_byte_sha256"]) == ("metadata-only", NEW_BYTES_SHA)


def test_on_diff_on_setting_is_unchanged(tmp_path, monkeypatch) -> None:
    result = _approve(tmp_path, monkeypatch, _on_diff(), setting=True)
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["method"] == "metadata-only-resave"


def test_off_diff_off_setting_is_unchanged(tmp_path, monkeypatch) -> None:
    diff = {**bucket_diff(), "auto_approve_metadata_resaves": False}
    diff["renames_metadata_only"] = []
    result = _approve(tmp_path, monkeypatch, diff, setting=False)
    assert result.exit_code == 0, result.output


def test_legacy_diff_without_the_field_is_treated_as_off(tmp_path, monkeypatch) -> None:
    result = _approve(tmp_path, monkeypatch, bucket_diff(), setting=False)
    assert result.exit_code == 0, result.output  # no mismatch: off against off
    assert "held:" in result.output


def test_on_diff_with_no_resave_rows_does_not_refuse(tmp_path, monkeypatch) -> None:
    diff = {**bucket_diff(), "auto_approve_metadata_resaves": True, "renames_metadata_only": []}
    result = _approve(tmp_path, monkeypatch, diff, setting=False)
    assert result.exit_code == 0, result.output


def test_explicit_approve_rename_of_a_moved_row_records_its_evidence(tmp_path, monkeypatch) -> None:
    # After re-running with the setting off the row is a quarantined row with
    # evidence; --approve-rename then carries that evidence onto the alias.
    from tests.unit.test_resave_held_evidence import _held_diff
    diff = {**_held_diff(), "auto_approve_metadata_resaves": False}
    result = _approve(tmp_path, monkeypatch, diff, setting=False,
                      extra=("--approve-rename", f"{NEW_ID}={OLD_ID}"))
    assert result.exit_code == 0, result.output
    [alias] = json.loads((tmp_path / "aliases.json").read_text())["aliases"]
    assert alias["change_nature"] == "metadata-only"
