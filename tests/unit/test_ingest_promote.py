"""Tests for the promote-and-build path extracted from ``ingest_cli.py``
(R7C.2 / #169): gate + snapshot resolution, and promote-then-report,
including the builder-failure -> non-zero-exit contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import typer

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.cli.ingest_promote import (  # noqa: E402
    promote_and_report,
    resolve_approved_snapshot,
)


def _write_log(log: Path, tranche: str) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"tranche_sha256": tranche}) + "\n")


def test_resolve_approved_snapshot_exits_1_when_not_approved(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    log.write_text("")
    with pytest.raises(typer.Exit) as exc:
        resolve_approved_snapshot("abc123", log, tmp_path / "snaps", tmp_path / "diffs")
    assert exc.value.exit_code == 1


def test_resolve_approved_snapshot_exits_2_when_no_snapshot(tmp_path: Path) -> None:
    tranche = "abc123" + "0" * 58
    log = tmp_path / "log.jsonl"
    _write_log(log, tranche)
    snapshots_dir = tmp_path / "snaps"
    snapshots_dir.mkdir()
    with pytest.raises(typer.Exit) as exc:
        resolve_approved_snapshot(tranche, log, snapshots_dir, tmp_path / "diffs")
    assert exc.value.exit_code == 2


def test_resolve_approved_snapshot_returns_snapshot_path(tmp_path: Path) -> None:
    tranche = "abc123" + "0" * 58
    log = tmp_path / "log.jsonl"
    _write_log(log, tranche)
    snapshots_dir = tmp_path / "snaps"
    snapshots_dir.mkdir()
    target = snapshots_dir / f"{tranche}.json"
    target.write_text("{}")
    assert resolve_approved_snapshot(tranche, log, snapshots_dir, tmp_path / "diffs") == target


def test_promote_and_report_promotes_and_prints(tmp_path: Path, capsys) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "abc", "cards": []}')
    manifest = tmp_path / "latest.json"

    promote_and_report(snapshot, manifest)

    assert manifest.read_text() == snapshot.read_text()
    out = capsys.readouterr().out
    assert "promoted snapshot" in out


def test_promote_and_report_exits_nonzero_naming_builder_but_keeps_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A builder failure during a real run must no longer be merely
    advisory -- it must exit non-zero and name the builder, while the
    manifest promotion itself (already recorded) stands."""
    import subprocess

    repo_root = tmp_path / "repo"
    (repo_root / "data" / "manifests").mkdir(parents=True)
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "build_video_posters.py").write_text("#!/usr/bin/env python\n")
    (scripts_dir / "build_pdf_thumbs.py").write_text("#!/usr/bin/env python\n")

    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "abc", "cards": []}')
    manifest = pipeline / "latest.json"

    def _fake_run(cmd, *args, **kwargs):
        if "build_video_posters.py" in " ".join(cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="r2 mirror missing")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(typer.Exit) as exc:
        promote_and_report(snapshot, manifest)

    assert exc.value.exit_code == 1
    # The manifest promotion already stands, regardless of the exit.
    assert manifest.exists()
    assert manifest.read_text() == snapshot.read_text()
    captured = capsys.readouterr()
    assert "build_video_posters.py" in captured.out + captured.err
