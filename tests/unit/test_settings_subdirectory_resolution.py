"""``Settings.data_root`` gives the same answer from any working directory.

The CLI is run from the repo root, from a subdirectory, and from wherever an
operator happens to be standing, and all three must find the same data. These
tests check the answer against a repo root the test knows from its own location
on disk — this file sits at ``<repo>/tests/unit/`` — rather than against the
package's location, so they verify where ``data_root`` lands instead of
restating how it is computed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.config.settings import Settings

# The checkout this test file belongs to: <repo>/tests/unit/<this file>.
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATA_ROOT = REPO_ROOT / "data"


def _pristine_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with no environment or dotenv contribution to ``data_root``."""
    monkeypatch.delenv("PURSUE_DATA_ROOT", raising=False)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_repo_root_fixture_is_this_checkout() -> None:
    """The expected root really is this project's checkout, not some ancestor."""
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "src" / "pursue_index" / "__init__.py").is_file()


def test_default_data_root_is_this_checkouts_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing configured, ``data_root`` is this checkout's ``data``."""
    assert _pristine_settings(monkeypatch).data_root == EXPECTED_DATA_ROOT


def test_data_root_is_unchanged_when_invoked_from_a_subdirectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running from inside the repo gives the same absolute answer."""
    monkeypatch.chdir(REPO_ROOT / "src")
    resolved = _pristine_settings(monkeypatch).data_root
    assert resolved == EXPECTED_DATA_ROOT
    assert resolved != Path.cwd() / "data"


def test_data_root_is_unchanged_when_invoked_from_outside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A working directory outside the checkout does not move the data root."""
    monkeypatch.chdir(tmp_path)
    resolved = _pristine_settings(monkeypatch).data_root
    assert resolved == EXPECTED_DATA_ROOT
    assert tmp_path not in resolved.parents


def test_an_unrelated_project_directory_does_not_capture_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standing in another project does not make its directory our data root.

    A neighbouring project carries its own project file; the anchor is the
    checkout this package was imported from, so the answer does not follow the
    operator around.
    """
    neighbour = tmp_path / "another-project"
    (neighbour / "src").mkdir(parents=True)
    (neighbour / "pyproject.toml").write_text("[project]\nname = 'another'\n")
    monkeypatch.chdir(neighbour / "src")

    assert _pristine_settings(monkeypatch).data_root == EXPECTED_DATA_ROOT


def test_configured_data_root_wins_over_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PURSUE_DATA_ROOT`` names the data root outright; production sets it."""
    custom_data = tmp_path / "custom-data"
    monkeypatch.setenv("PURSUE_DATA_ROOT", str(custom_data))

    assert Settings().data_root == custom_data
