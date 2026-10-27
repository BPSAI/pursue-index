"""The snapshot job publishes the tranche diff and tranche-ready record (R7C.31).

Structure pins on ``.github/workflows/poll-pursue.yml``'s ``snapshot`` job:

* the generate step writes both outputs into the dirs the commit step
  stages, and the commit step stages them in the SAME ``git add`` as the
  existing snapshot/diff artifacts -- one job, one commit;
* the lane stays on the hash-locked poll install: exactly one install step,
  ``--require-hashes -r requirements-poll.txt``, and nothing else installed;
* a refused record opens a poll failure issue whose body is the script's
  ``--error-out`` file (which names the failing field);
* the tranche issue number is looked up before the record is built, the
  same immediately-consistent way the verdict step finds it.

Credential isolation for the whole job is pinned in
``test_poll_pursue_workflow.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "poll-pursue.yml"
_STAGED = ("data/manifests/snapshots", "web/public/data/snapshots", "data/manifests/diffs",
           "data/tranche-diffs", "data/tranche-ready")


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["snapshot"]["steps"]


def _step(needle: str) -> tuple[int, dict]:
    for i, s in enumerate(_steps()):
        if needle in " ".join(str(s.get(k, "")) for k in ("name", "id")):
            return i, s
    raise AssertionError(f"no snapshot step matching {needle!r}")


def _flag(run: str, flag: str) -> str:
    match = re.search(rf"{re.escape(flag)}\s+\"?([^\s\"\\]+)", run)
    assert match, f"{flag} missing"
    return match.group(1)


def test_the_commit_step_stages_both_new_outputs_with_the_existing_artifacts() -> None:
    _, commit = _step("Commit snapshot")
    run = str(commit["run"])
    assert all(path in run for path in _STAGED)
    assert run.count("git commit") == 1, "one job, one commit"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def test_the_commit_step_survives_a_missing_output_dir(tmp_path: Path) -> None:
    """``data/tranche-ready`` does not exist until a record is written (bootstrap,
    or a refused record): ``git add`` on a missing pathspec is fatal under ``bash -e``."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", str(origin), str(work))
    _git(work, "checkout", "-b", "main")
    (work / "seed.txt").write_text("seed")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "add", "seed.txt")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "seed")
    _git(work, "push", "origin", "main")
    snap = work / "data" / "manifests" / "snapshots"
    snap.mkdir(parents=True)
    (snap / "s.json").write_text("{}")
    _, commit = _step("Commit snapshot")
    result = subprocess.run(["bash", "-e", "-c", str(commit["run"])], cwd=work,
                            env={**os.environ, "NEW_SHA": "a" * 64},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "snapshot + diff" in _git(work, "log", "-1", "--format=%s")
    assert "data/manifests/snapshots/s.json" in _git(work, "ls-files")


def test_the_generate_step_writes_the_outputs_where_the_commit_step_stages_them() -> None:
    _, gen = _step("Generate snapshot")
    run = str(gen["run"])
    assert _flag(run, "--tranche-ready-dir") == "data/tranche-ready"
    assert _flag(run, "--tranche-diff-dir") == "data/tranche-diffs"
    assert "--error-out" in run


def test_the_snapshot_job_installs_only_the_hash_locked_poll_set() -> None:
    installs = [s for s in _steps() if re.search(r"\b(pip|uv|poetry)\b.*\binstall\b",
                                                 str(s.get("run", "")))]
    assert len(installs) == 1, "the snapshot job must have exactly one install step"
    lines = [ln.strip() for ln in str(installs[0]["run"]).splitlines()
             if re.search(r"\binstall\b", ln)]
    package_installs = [ln for ln in lines if "--upgrade pip" not in ln]
    assert package_installs == ["python -m pip install --require-hashes -r requirements-poll.txt"]


def test_a_refused_record_opens_a_failure_issue_naming_the_field() -> None:
    gen_idx, gen = _step("Generate snapshot")
    error_out = _flag(str(gen["run"]), "--error-out")
    idx, step = _step("tranche-ready failure")
    assert idx > gen_idx
    assert "failure()" in str(step["if"]) and f"steps.{gen['id']}.outcome" in str(step["if"])
    run = str(step["run"])
    assert "gh issue create" in run and "tranche-poll-failure" in run
    assert error_out in run and "--body-file" in run


def test_the_tranche_issue_is_looked_up_before_the_record_is_built() -> None:
    gen_idx, gen = _step("Generate snapshot")
    idx, lookup = _step("Locate tranche issue")
    assert idx < gen_idx
    run = str(lookup["run"])
    assert "--json" in run and "--arg s" in run and "--limit" in run and "--search" not in run
    assert lookup.get("continue-on-error") is True
    assert f"steps.{lookup['id']}.outputs.number" in str(gen.get("env", {}))
    assert "--tranche-issue" in str(gen["run"]) and "--poll-commit" in str(gen["run"])
