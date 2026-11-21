"""The gate beside an older gate or allowlist, run through the workflow.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.web_audit_support import (
    ALLOWLIST,
    FIXTURES,
    REAL_LOCK,
    ROOT,
    SCRIPT,
    WEB_LOCK,
    _report,
    _vuln,
    _wf,
    gate,
)

# --- the gate step, run through the workflow ------------------------------
#
# The workflow passes the full arguments to the selected gate and no longer
# probes its --help: main's gate understands --lockfile and --runtime, and an
# unknown flag fails the step.

HELPERS = sorted((ROOT / "scripts").glob("_web_audit_*.py"))


def _vite_high_report() -> dict:
    return _report(_vuln("vite", "high", "GHSA-vite-0000-0000"))


def _gate_step(name: str) -> dict:
    steps = _wf()["jobs"]["audit"]["steps"]
    found = [s for s in steps if s.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def _run_gate_step(step_name: str, gate: Path, allow: Path, tmp: Path, report: dict):
    """Run the workflow's own gate step, as the runner would, in a repo-root cwd."""
    (tmp / "audit.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp / "worker-audit.json").write_text(json.dumps(report), encoding="utf-8")
    env = {**os.environ, "GATE": str(gate), "ALLOWLIST": str(allow), "RUNNER_TEMP": str(tmp)}
    return subprocess.run(
        ["bash", "-e", "-c", _gate_step(step_name)["run"]],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )


def _copy_gate(tmp: Path) -> Path:
    """The current gate beside its helper, like the base-commit copy in RUNNER_TEMP."""
    dest = tmp / "gate"
    dest.mkdir()
    (dest / "web_audit_gate.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    for helper in HELPERS:
        (dest / helper.name).write_text(helper.read_text(encoding="utf-8"), encoding="utf-8")
    return dest / "web_audit_gate.py"


def test_the_committed_allowlist_is_in_the_current_shape():
    assert "legacy" not in gate.load_allowlist(ALLOWLIST)


def test_the_gate_runs_from_a_bare_directory_beside_its_helper(tmp_path):
    g = _copy_gate(tmp_path)
    f = tmp_path / "a.json"
    f.write_text(json.dumps(_report()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-I", str(g), str(f), "--allowlist", str(ALLOWLIST),
         "--lockfile", str(WEB_LOCK)],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("step", ["Gate", "Gate (Worker, runtime)"])
def test_the_current_gate_runs_through_the_workflow_on_a_clean_report(step, tmp_path):
    r = _run_gate_step(step, _copy_gate(tmp_path), ALLOWLIST, tmp_path, _report())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr


def test_an_old_shape_allowlist_fails_closed_with_a_message(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"build_only": {"vite": "reason"}}), encoding="utf-8")
    r = _run_gate_step("Gate", _copy_gate(tmp_path), old, tmp_path, _report())
    assert r.returncode != 0
    assert "Traceback" not in r.stdout + r.stderr
    assert "exact name@version" in r.stdout + r.stderr


def test_a_gate_that_lacks_a_flag_fails_the_step(tmp_path):
    stub = tmp_path / "old_gate.py"
    stub.write_text(
        "import argparse\nap = argparse.ArgumentParser()\n"
        "ap.add_argument('audit'); ap.add_argument('--allowlist')\nap.parse_args()\n",
        encoding="utf-8",
    )
    for step in ("Gate", "Gate (Worker, runtime)"):
        r = _run_gate_step(step, stub, ALLOWLIST, tmp_path, _report())
        assert r.returncode != 0, step


def test_the_current_gate_exempts_a_build_only_package_through_the_workflow(tmp_path):
    g = _copy_gate(tmp_path)
    r = _run_gate_step("Gate", g, ALLOWLIST, tmp_path, _vite_high_report())
    assert r.returncode == 0, r.stdout + r.stderr
    w = _run_gate_step("Gate (Worker, runtime)", g, ALLOWLIST, tmp_path, _vite_high_report())
    assert w.returncode == 1, w.stdout


def test_the_probe_flags_exist_in_the_current_gate_help():
    out = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert "--lockfile" in out and "--runtime" in out
