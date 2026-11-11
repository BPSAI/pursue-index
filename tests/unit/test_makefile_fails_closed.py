"""The Makefile fails a target when a step piped through ``| tail`` fails.

Under make's default ``/bin/sh -c`` a pipeline reports only its last
command's status, so ``npm run build 2>&1 | tail -3`` succeeded whenever
``tail`` did. These tests drive the real Makefile with a fake ``npm`` first
on ``PATH``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

pytestmark = pytest.mark.skipif(
    shutil.which("make") is None or not Path("/bin/bash").exists(),
    reason="needs make and /bin/bash",
)


def _fake_npm(bin_dir: Path, exit_code: int) -> None:
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "echo 'fake build line 1'\n"
        "echo 'fake build error detail' >&2\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)


def _make_astro_build(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(REPO_ROOT), "astro-build"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_astro_build_fails_when_npm_build_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _fake_npm(bin_dir, exit_code=3)

    result = _make_astro_build(bin_dir)

    assert result.returncode != 0, result.stdout + result.stderr
    # The full build output is shown on failure, not just a tail.
    assert "fake build error detail" in result.stdout


def test_astro_build_passes_when_npm_build_passes(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _fake_npm(bin_dir, exit_code=0)

    result = _make_astro_build(bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr


def test_recipes_run_under_bash_with_errexit_and_pipefail() -> None:
    """Covers every ``| tail`` builder line in rebuild-derivatives, not
    only astro-build: they all depend on these two settings."""
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^SHELL := /bin/bash$", text, re.M)
    shellflags = re.search(r"^\.SHELLFLAGS := (.+)$", text, re.M)
    assert shellflags is not None
    flags = shellflags.group(1).split()
    assert flags[-1] == "-c"
    assert "-e" in flags or any(f.startswith("-") and "e" in f for f in flags[:-1])
    assert "pipefail" in flags


def test_a_failing_pipeline_head_fails_a_make_recipe(tmp_path: Path) -> None:
    """Behavioural check of the shell settings, independent of any builder."""
    mk = tmp_path / "probe.mk"
    shell_lines = [
        ln for ln in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if ln.startswith(("SHELL :=", ".SHELLFLAGS :="))
    ]
    mk.write_text(
        "\n".join(shell_lines) + "\nprobe:\n\t@false | tail -1\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["make", "--no-print-directory", "-f", str(mk), "probe"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode != 0
