"""The production runner bounds every command and kills its whole group."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from pursue_index.tranche_autopilot.runner import SubprocessRunner, pursue_argv


def test_pursue_runs_as_this_interpreter() -> None:
    assert pursue_argv(["pursue", "storage", "verify"]) == [
        sys.executable, "-m", "pursue_index.cli.commands", "storage", "verify"]
    assert pursue_argv(["make", "ship-ready"]) == ["make", "ship-ready"]


def test_timeout_kills_the_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "late"
    script = f"(sleep 2; touch {marker}) & sleep 30"
    started = time.monotonic()
    result = SubprocessRunner()(["sh", "-c", script], cwd=tmp_path, timeout=0.5)
    assert result.returncode == 124
    assert time.monotonic() - started < 10
    time.sleep(2.5)
    assert not marker.exists()  # the backgrounded grandchild died with the group


def test_missing_executable_is_a_failed_command(tmp_path: Path) -> None:
    result = SubprocessRunner()(["no-such-binary-xyz"], cwd=tmp_path, timeout=5)
    assert result.returncode == 127


def test_output_is_captured(tmp_path: Path) -> None:
    result = SubprocessRunner()(["sh", "-c", "echo out; echo err >&2; exit 3"],
                                cwd=tmp_path, timeout=5)
    assert (result.returncode, result.stdout, result.stderr) == (3, "out\n", "err\n")
