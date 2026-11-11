"""The injectable command runner.

Every external command the autopilot issues goes through a :class:`Runner`:
``SubprocessRunner`` in production, a recording fake in tests. This module is
the only place in the package that starts a process.
"""

from __future__ import annotations

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

    A timeout or a missing executable is reported as a failed command
    (returncode 124 / 127), never raised, so the engine records it as the
    step's failure.
    """

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        try:
            done = subprocess.run(  # argv list, no shell
                pursue_argv(argv), cwd=cwd, timeout=timeout, env=dict(env) if env else None,
                capture_output=True, text=True, check=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", f"timed out after {timeout:.0f}s")
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        return CommandResult(done.returncode, done.stdout, done.stderr)
