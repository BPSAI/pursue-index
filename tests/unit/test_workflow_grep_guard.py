"""Every ``grep -c`` in a workflow run step is guarded, so a quiet day stays green."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = [
    ".github/workflows/verify-assets-daily.yml",
    ".github/workflows/verify-assets-weekly.yml",
    ".github/workflows/poll-pursue.yml",
]


def _run_steps(path: str):
    doc = yaml.safe_load((ROOT / path).read_text())
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                yield step.get("name", "?"), step["run"]


def _grep_c_steps():
    for path in WORKFLOWS:
        for name, script in _run_steps(path):
            if re.search(r"grep\s+-[a-zA-Z]*c", script):
                yield pytest.param(path, name, script, id=f"{Path(path).stem}:{name}")


@pytest.mark.parametrize(("path", "name", "script"), list(_grep_c_steps()))
def test_every_grep_count_is_guarded(path, name, script):
    for line in script.splitlines():
        if re.search(r"grep\s+-[a-zA-Z]*c", line):
            assert "|| true" in line, f"{path}:{name}: unguarded: {line}"


@pytest.mark.parametrize(("path", "name", "script"), list(_grep_c_steps()))
def test_grep_count_step_exits_zero_under_bash_e_with_no_new_rows(path, name, script, tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    git = shim / "git"
    # `diff --cached --quiet` must report changes (exit 1) so the commit branch runs;
    # the registry diff itself is empty, so grep -c counts 0 rows.
    git.write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = "--quiet" ] && exit 1; done\nexit 0\n')
    git.chmod(0o755)
    wt = tmp_path / "wt"
    (wt / "data").mkdir(parents=True)  # no registry file: skips the python step
    env = {
        "PATH": f"{shim}:{os.environ['PATH']}",
        "WT": str(wt),
        "VERIFY_BRANCH": "verify/registry",
        "POLL_BRANCH": "poll/x",
        "GITHUB_OUTPUT": str(tmp_path / "out"),
        "HOME": str(tmp_path),
    }
    work = tmp_path / "cwd"
    (work / "data").mkdir(parents=True)
    r = subprocess.run(
        ["bash", "-e", "-c", script], env=env, cwd=work, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
