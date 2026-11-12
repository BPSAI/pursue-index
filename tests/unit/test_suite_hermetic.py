"""The suite's isolation from the invoking shell (tests/conftest.py) holds
for logging configured at package import and for subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

_PRINT_DATA_ROOT = (
    "from pursue_index.config import settings\n"
    "try:\n"
    "    print('data_root=' + str(settings.data_root))\n"
    "except Exception as exc:\n"
    "    print('data_root unresolved: ' + type(exc).__name__)\n"
)


def _child_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "NO_PURSUE_DOTENV"}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC), os.environ.get("PYTHONPATH", "")) if p
    )
    env.update(extra)
    return env


def test_shell_log_level_does_not_suppress_a_logged_event() -> None:
    """``pursue_index`` configures logging from settings when it is first
    imported. A shell exporting PURSUE_LOG_LEVEL=CRITICAL must not reach
    that configuration and drop the info event this test asserts on."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
            "tests/unit/test_transcribe_eligibility.py::test_rejected_link_is_logged",
        ],
        cwd=REPO_ROOT,
        env=_child_env(PURSUE_LOG_LEVEL="CRITICAL"),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_subprocess_does_not_read_a_dotenv_in_its_working_directory(
    tmp_path: Path,
) -> None:
    """The conftest exports NO_PURSUE_DOTENV, so a script or CLI spawned
    by a test ignores a ``.env`` in its working directory."""
    (tmp_path / ".env").write_text("PURSUE_DATA_ROOT=/canary\n", encoding="utf-8")
    assert os.environ.get("NO_PURSUE_DOTENV") == "1"

    result = subprocess.run(
        [sys.executable, "-c", _PRINT_DATA_ROOT],
        cwd=tmp_path,
        env={**_child_env(), "NO_PURSUE_DOTENV": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "/canary" not in result.stdout + result.stderr


def test_without_the_switch_a_subprocess_does_read_that_dotenv(tmp_path: Path) -> None:
    """Control for the test above: the same child, without the switch,
    reads the ``.env`` -- so the absence of /canary there is the switch."""
    (tmp_path / ".env").write_text("PURSUE_DATA_ROOT=/canary\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-c", _PRINT_DATA_ROOT],
        cwd=tmp_path,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "data_root=/canary" in result.stdout, result.stdout + result.stderr
