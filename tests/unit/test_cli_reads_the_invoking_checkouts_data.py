"""A data command reads the checkout it is invoked from, not the one its
editable install was built against (R7C.4, acceptance criterion 1).

An editable install's ``sys.path`` entry stays pinned to whichever
checkout ran ``pip install -e .``. Before ``pursue_index.paths.repo_root()``,
every ``_REPO_ROOT``-style constant was derived from that installing
checkout's own ``__file__``, so a command run with its current directory
set to a SECOND checkout (a worktree, a fixture repo) still silently read
and wrote the first one's ``data/``. This test proves the fix with a real
subprocess -- not a monkeypatched cwd in-process -- because the bug is
specifically about what a freshly-started process resolves, which an
in-process ``CliRunner`` invocation (module already imported, ``_REPO_ROOT``
already bound) cannot exercise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHA = "deadbeef" * 8  # 64 hex chars; present only in the second checkout's log


# Variables that change which code a child Python imports. A caller's
# relative ``PYTHONPATH=src`` would resolve against the fixture checkout's
# stub package, so every child starts without them.
_IMPORT_PATH_LEAKS = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE")


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _IMPORT_PATH_LEAKS}
    env.update(extra)
    return env


def _make_second_checkout(root: Path) -> None:
    """A standalone pursue-index-shaped checkout with its own approval log,
    carrying an approval this process's real checkout does not have."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    data_dir = root / "data"
    data_dir.mkdir()
    row = {"tranche_sha256": _SHA, "approved_at": "2026-01-01T00:00:00Z", "note": "fixture"}
    (data_dir / "tranche-approval-log.jsonl").write_text(json.dumps(row) + "\n")


def test_ingest_check_reads_the_checkout_named_by_the_operator_override(
    tmp_path: Path,
) -> None:
    """``PURSUE_REPO_ROOT`` is the explicit way to point a data command at
    another checkout's ``data/``."""
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_second_checkout(second_checkout)

    env = _clean_env(PURSUE_REPO_ROOT=str(second_checkout))

    result = subprocess.run(
        [sys.executable, "-m", "pursue_index.cli.ingest_cli", "check", "--tranche", _SHA],
        cwd=second_checkout,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "approved" in result.stdout


def test_ingest_check_refuses_a_checkout_the_install_does_not_own(tmp_path: Path) -> None:
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_second_checkout(second_checkout)

    env = _clean_env()
    env.pop("PURSUE_REPO_ROOT", None)

    result = subprocess.run(
        [sys.executable, "-m", "pursue_index.cli.ingest_cli", "check", "--tranche", _SHA],
        cwd=second_checkout,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "not the installed checkout" in result.stderr


def test_a_relative_pythonpath_in_the_caller_does_not_reach_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PYTHONPATH=src`` set by a caller must not make the child import the
    fixture checkout's stub ``src/pursue_index``."""
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_second_checkout(second_checkout)
    monkeypatch.setenv("PYTHONPATH", "src")

    env = _clean_env(PURSUE_REPO_ROOT=str(second_checkout))
    result = subprocess.run(
        [sys.executable, "-m", "pursue_index.cli.ingest_cli", "check", "--tranche", _SHA],
        cwd=second_checkout,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
