"""The injectable command runner.

Every external command the autopilot issues goes through a :class:`Runner`:
``SubprocessRunner`` in production, a recording fake in tests. This module is
the only place in the package that starts a process.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = ["PURSUE", "CommandResult", "Runner", "SubprocessRunner", "pursue_argv"]

# Logical program name used in step records; resolved to the running
# interpreter's own CLI so a child never picks up another checkout's install.
PURSUE = "pursue"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Runner(Protocol):
    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


def pursue_argv(argv: Sequence[str]) -> list[str]:
    """``pursue ...`` as the interpreter that is running this code."""
    if argv and argv[0] == PURSUE:
        return [sys.executable, "-m", "pursue_index.cli.commands", *argv[1:]]
    return list(argv)


class SubprocessRunner:
    """Run a command, capture its output, and bound it with ``timeout``.

    Each command gets its own process group, and a timeout kills the whole
    group: ``make`` and ``npm`` fork children that would otherwise keep
    writing into the checkout after the step was reported failed. A timeout
    or a missing executable is reported as a failed command (returncode 124 /
    127), never raised, so the engine records it as the step's failure.
    """

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        try:
            proc = subprocess.Popen(  # argv list, no shell
                pursue_argv(argv), cwd=cwd, env=dict(env) if env is not None else None,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            return CommandResult(124, "", f"timed out after {timeout:.0f}s")
        return CommandResult(proc.returncode, out, err)


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL the process group this runner created for ``proc``, then reap it."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.communicate()
