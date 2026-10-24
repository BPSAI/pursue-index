"""Run git against a checkout whose own configuration is not trusted.

A repository's local config can name programs git will execute (for
example ``core.fsmonitor``). Any git call aimed at a directory we did not
create goes through here so those hooks stay off and the system config is
ignored.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

__all__ = ["GitUnavailableError", "run_git"]

_HARDENING = ("-c", "core.fsmonitor=")


class GitUnavailableError(RuntimeError):
    """git could not be run at all (missing binary or timeout)."""


def run_git(
    repo: Path, *args: str, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    """``git -C <repo> <args>`` with fsmonitor disabled and no system config."""
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}
    cmd = ["git", *_HARDENING, "-C", str(repo), *args]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise GitUnavailableError(f"git {args[0] if args else ''} failed: {exc}") from exc
