"""Executable paths follow the installed package, never the working
directory, and the CLI does not print the resolved root."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.ocr.dots import _worker_script_default
from pursue_index.paths import installed_scripts_dir


def test_dots_worker_default_ignores_cwd_and_env_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dots_worker.py").write_text("raise SystemExit(99)\n")
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    worker = Path(_worker_script_default())

    assert worker == installed_scripts_dir() / "dots_worker.py"  # type: ignore[operator]
    assert tmp_path not in worker.parents


def test_cli_does_not_print_the_resolved_repo_root(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["ingest", "check", "--tranche", "0" * 64])

    assert "repo root" not in result.output
    assert str(Path.cwd()) not in result.output
