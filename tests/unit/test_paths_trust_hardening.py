"""Trust checks on the working directory: a planted ``.git`` link cannot pass
for a registered worktree, git probes ignore ambient ``GIT_*`` variables, and
an untrusted root is reported as one line at the CLI boundary, not at import."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pursue_index import paths, safe_git
from pursue_index.paths import UntrustedRootError, repo_root

SRC = Path(__file__).resolve().parents[2] / "src"


def _checkout(root: Path) -> None:
    (root / "src" / "pursue_index").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    (root / "src" / "pursue_index" / "__init__.py").write_text("")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _installed_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    installed = tmp_path / "installed"
    installed.mkdir()
    _checkout(installed)
    _git(installed, "init", "-q")
    _git(installed, "config", "user.email", "t@example.com")
    _git(installed, "config", "user.name", "T")
    _git(installed, "add", "-A")
    _git(installed, "commit", "-q", "-m", "init")
    real = tmp_path / "real-wt"
    _git(installed, "worktree", "add", "-q", "-b", "wt", str(real))
    return installed, real


def _plant(tmp_path: Path, gitdir: Path) -> Path:
    planted = tmp_path / "planted"
    planted.mkdir()
    _checkout(planted)
    (planted / ".git").write_text(f"gitdir: {gitdir}\n")
    return planted


def test_real_worktree_is_still_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed, real = _installed_with_worktree(tmp_path)
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    monkeypatch.setattr(paths, "installed_checkout_root", lambda: installed)
    monkeypatch.chdir(real)

    assert repo_root() == real.resolve()


def test_dir_linked_to_a_registered_worktrees_gitdir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed, _ = _installed_with_worktree(tmp_path)
    planted = _plant(tmp_path, installed / ".git" / "worktrees" / "real-wt")
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    monkeypatch.setattr(paths, "installed_checkout_root", lambda: installed)
    monkeypatch.chdir(planted)

    with pytest.raises(UntrustedRootError):
        repo_root()


def test_dir_linked_straight_to_the_installed_git_dir_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed, _ = _installed_with_worktree(tmp_path)
    planted = _plant(tmp_path, installed / ".git")
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    monkeypatch.setattr(paths, "installed_checkout_root", lambda: installed)
    monkeypatch.chdir(planted)

    with pytest.raises(UntrustedRootError):
        repo_root()


def test_git_probe_ignores_ambient_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
    for d in (here, elsewhere):
        d.mkdir()
        _git(d, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))

    out = safe_git.run_git(here, "rev-parse", "--show-toplevel").stdout.strip()

    assert Path(out).resolve() == here.resolve()


def test_cli_from_an_untrusted_checkout_prints_one_line_and_no_traceback(
    tmp_path: Path,
) -> None:
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    _checkout(stranger)
    _git(stranger, "init", "-q")
    code = (
        "from pursue_index.cli.commands import app; "
        "app(['ingest', 'check', '--tranche', '0' * 64])"
    )

    proc = subprocess.run(
        [sys.executable, "-P", "-c", code],
        cwd=stranger,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), "HOME": str(tmp_path)},
        check=False,
    )

    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "not the installed checkout" in proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1
