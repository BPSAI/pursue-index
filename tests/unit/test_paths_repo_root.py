"""``pursue_index.paths.repo_root()`` -- the one resolver every
``_REPO_ROOT``-style constant must route through (R7C.4 / #169-adjacent).

An editable install's ``sys.path`` entry stays pinned to whichever checkout
ran ``pip install -e .``, so importing ``pursue_index`` from a second
worktree or a test fixture otherwise still resolves ``data/`` beside the
ORIGINAL checkout rather than the one the process is actually running in.
``repo_root()`` fixes that by preferring the *running* checkout (found via
the current directory's git top level) over the *imported* one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pursue_index import paths
from pursue_index.paths import UntrustedRootError, repo_root


def _make_pursue_index_checkout(root: Path) -> None:
    """A minimal directory layout that looks like a pursue-index checkout."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def _git_commit_all(root: Path) -> None:
    for cmd in (
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=root, check=True)


def test_env_override_wins_outright(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "wherever-the-operator-says"
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(override))

    assert repo_root() == override.resolve()


def test_env_override_wins_even_from_inside_a_real_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PURSUE_REPO_ROOT`` beats BOTH the cwd-detected checkout and the
    package-location fallback -- it is not just a tiebreaker."""
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_pursue_index_checkout(second_checkout)
    _git_init(second_checkout)
    monkeypatch.chdir(second_checkout)

    override = tmp_path / "an-entirely-different-place"
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(override))

    assert repo_root() == override.resolve()
    assert repo_root() != second_checkout.resolve()


def test_cwd_in_a_registered_worktree_of_the_installed_checkout_resolves_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    installed = tmp_path / "installed"
    installed.mkdir()
    _make_pursue_index_checkout(installed)
    _git_init(installed)
    _git_commit_all(installed)
    worktree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt", str(worktree)],
        cwd=installed, check=True,
    )
    monkeypatch.setattr(paths, "installed_checkout_root", lambda: installed)
    monkeypatch.chdir(worktree / "src")

    assert repo_root() == worktree.resolve()


def test_cwd_in_an_unrelated_pursue_looking_checkout_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pursue-index-shaped clone that is not the installed checkout or
    one of its worktrees must not become the root: it could carry its own
    scripts and git config."""
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    installed = tmp_path / "installed"
    installed.mkdir()
    _make_pursue_index_checkout(installed)
    _git_init(installed)
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    _make_pursue_index_checkout(stranger)
    _git_init(stranger)
    monkeypatch.setattr(paths, "installed_checkout_root", lambda: installed)
    monkeypatch.chdir(stranger)

    with pytest.raises(UntrustedRootError, match="not the installed checkout"):
        repo_root()


def test_installed_scripts_dir_ignores_cwd_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stranger = tmp_path / "stranger"
    (stranger / "scripts").mkdir(parents=True)
    _make_pursue_index_checkout(stranger)
    _git_init(stranger)
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(stranger))
    monkeypatch.chdir(stranger)

    scripts = paths.installed_scripts_dir()

    assert scripts is None or scripts.parent != stranger.resolve()


def test_git_probe_runs_with_fsmonitor_off_and_no_system_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pursue_index import safe_git

    seen: dict[str, object] = {}
    real_run = subprocess.run

    def spy(cmd, **kw):  # type: ignore[no-untyped-def]
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return real_run(cmd, **kw)

    monkeypatch.setattr(safe_git.subprocess, "run", spy)
    _git_init(tmp_path)
    safe_git.run_git(tmp_path, "rev-parse", "--git-common-dir")

    assert "core.fsmonitor=" in seen["cmd"]  # type: ignore[operator]
    assert seen["env"]["GIT_CONFIG_NOSYSTEM"] == "1"  # type: ignore[index]


def test_cwd_outside_any_checkout_falls_back_to_the_package_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    import pursue_index
    expected = Path(pursue_index.__file__).resolve().parents[2]

    assert repo_root() == expected


def test_cwd_in_an_unrelated_git_repo_falls_back_to_the_package_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git repo that is not a pursue-index checkout (no sentinel + src
    layout) must not be mistaken for one just because it has a ``.git``."""
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    unrelated = tmp_path / "some-other-project"
    unrelated.mkdir()
    (unrelated / "pyproject.toml").write_text("[project]\nname = 'unrelated'\n")
    _git_init(unrelated)
    monkeypatch.chdir(unrelated)

    import pursue_index
    expected = Path(pursue_index.__file__).resolve().parents[2]

    assert repo_root() == expected
