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

from pursue_index.paths import repo_root


def _make_pursue_index_checkout(root: Path) -> None:
    """A minimal directory layout that looks like a pursue-index checkout."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


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


def test_cwd_in_a_second_checkout_resolves_to_that_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Standing inside a *different* pursue-index checkout (a second worktree,
    a fixture repo) resolves to THAT checkout, not the one this test's own
    package was imported from."""
    monkeypatch.delenv("PURSUE_REPO_ROOT", raising=False)
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_pursue_index_checkout(second_checkout)
    _git_init(second_checkout)

    subdir = second_checkout / "src"
    monkeypatch.chdir(subdir)

    resolved = repo_root()

    assert resolved == second_checkout.resolve()
    import pursue_index
    this_packages_checkout = Path(pursue_index.__file__).resolve().parents[2]
    assert resolved != this_packages_checkout


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
