"""``ingest approve``/``ingest run`` refuse a checkout behind the poller
(R7C.4, acceptance criterion 4).

Release 7 shipped from a main checkout six poll commits behind
``origin/main``: the approval gate had no way to notice its own
tranche-diff/snapshot inputs were stale. These tests pin the fix end to
end through the Typer commands, using a real git fixture (clone + a
divergent ``origin/main``) rather than mocking ``pursue_index.poll_freshness``
directly -- that module already has its own unit tests
(``test_poll_freshness.py``); this file is about the CLI wiring.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app

runner = CliRunner()

_SHA = "a1b2c3d4e5f6" + "0" * 52  # 64 hex chars


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _git_init_with_commit(root: Path) -> None:
    """A git repo that also *looks like* a pursue-index checkout, so
    ``pursue_index.paths.repo_root()``'s cwd-detection picks IT (and not
    this test's own checkout) once the test chdirs into it."""
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], root)
    _run(["git", "config", "user.email", "test@example.com"], root)
    _run(["git", "config", "user.name", "Test"], root)
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("")
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "last-known-csv-sha.txt").write_text("initial\n")
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-q", "-m", "initial"], root)


def _write_diff_artifact(repo_root: Path) -> None:
    diff_dir = repo_root / "data" / "tranche-diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(
        json.dumps({
            "tranche_sha256": _SHA,
            "summary": {"new_content": 0},
            "renames_confirmed": [],
            "new_content": [],
            "quarantined": [],
            "restored_unchanged": [],
            "restored_modified": [],
            "field_only_changes": [],
        }),
        encoding="utf-8",
    )


def _approve_args(repo_root: Path, *, extra: list[str] | None = None) -> list[str]:
    args = [
        "ingest", "approve",
        "--tranche", _SHA,
        "--note", "test approval",
        "--skip-audit",
        "--log", str(repo_root / "data" / "tranche-approval-log.jsonl"),
        "--aliases", str(repo_root / "data" / "card-aliases.json"),
        "--diff-dir", str(repo_root / "data" / "tranche-diffs"),
        "--snapshots-dir", str(repo_root / "data" / "manifests" / "snapshots"),
    ]
    return args + (extra or [])


@pytest.fixture
def behind_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clone whose local ``origin/main`` carries one poll-path commit the
    clone's own ``HEAD`` lacks."""
    origin = tmp_path / "origin"
    _git_init_with_commit(origin)
    clone = tmp_path / "clone"
    _run(["git", "clone", "-q", str(origin), str(clone)], tmp_path)
    _write_diff_artifact(clone)

    (origin / "data" / "last-known-csv-sha.txt").write_text("updated-by-poller\n")
    _run(["git", "add", "-A"], origin)
    _run(["git", "commit", "-q", "-m", "poll update"], origin)
    _run(["git", "fetch", "-q", "origin"], clone)

    monkeypatch.chdir(clone)
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    return clone


def test_approve_refuses_when_behind_naming_commit_count(behind_fixture: Path) -> None:
    result = runner.invoke(app, _approve_args(behind_fixture))

    assert result.exit_code != 0, result.output
    assert "1" in result.output
    assert "behind" in result.output
    assert not (behind_fixture / "data" / "tranche-approval-log.jsonl").exists()


def test_approve_allow_behind_with_reason_proceeds_and_writes_audit_row(
    behind_fixture: Path,
) -> None:
    result = runner.invoke(
        app,
        _approve_args(
            behind_fixture, extra=["--allow-behind", "--reason", "verified by hand"]
        ),
    )

    assert result.exit_code == 0, result.output
    approval_log = behind_fixture / "data" / "tranche-approval-log.jsonl"
    assert approval_log.exists()

    audit_log = behind_fixture / "data" / "poll-behind-audit-log.jsonl"
    rows = [json.loads(line) for line in audit_log.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["commit_count"] == 1
    assert rows[0]["reason"] == "verified by hand"


def test_approve_allow_behind_without_reason_is_rejected(behind_fixture: Path) -> None:
    result = runner.invoke(app, _approve_args(behind_fixture, extra=["--allow-behind"]))

    assert result.exit_code != 0, result.output
    assert not (behind_fixture / "data" / "tranche-approval-log.jsonl").exists()


def test_approve_proceeds_normally_when_caught_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin = tmp_path / "origin"
    _git_init_with_commit(origin)
    clone = tmp_path / "clone"
    _run(["git", "clone", "-q", str(origin), str(clone)], tmp_path)
    _write_diff_artifact(clone)
    monkeypatch.chdir(clone)
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)

    result = runner.invoke(app, _approve_args(clone))

    assert result.exit_code == 0, result.output
    assert (clone / "data" / "tranche-approval-log.jsonl").exists()
