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

# --- the gate beside an older gate or allowlist ---------------------------
#
# A PR is judged by the BASE commit's gate and allowlist, so while the gate
# schema changes the workflow meets every pairing of old and new. The legacy
# fixtures are main's gate and allowlist from before exact name@version
# entries, --lockfile and --runtime existed.

LEGACY_GATE = FIXTURES / "legacy_gate.py"
LEGACY_ALLOW = FIXTURES / "legacy_allowlist.json"
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
    assert gate.load_allowlist(ALLOWLIST)["legacy"] == []


def test_the_gate_reads_the_previous_allowlist_shape_and_says_so():
    allow = gate.load_allowlist(LEGACY_ALLOW)
    assert any("'vite'] is a bare package name" in n for n in allow["legacy"])
    assert any("GHSA-26w7-cxv4-gfx2" in n and "no review_by" in n for n in allow["legacy"])


def test_a_plain_string_acceptance_never_expires_but_is_reported(tmp_path):
    allow = gate.load_allowlist_data({"accepted_advisories": {"GHSA-x": "kept on purpose"}})
    crit = _report(_vuln("astro", "critical", "GHSA-x"))
    d = gate.decide(crit, allow, REAL_LOCK, today=datetime.date(2099, 1, 1))
    assert d.ok and d.accepted == ["GHSA-x"] and d.legacy


@pytest.mark.parametrize(
    "bad",
    [
        {"build_only": {"vite": ""}},
        {"build_only": {"not a name": "r"}},
        {"build_only": {"a/b/c": "r"}},
        {"accepted_advisories": {"GHSA-x": ""}},
        {"accepted_advisories": {"GHSA-x": 5}},
        {"accepted_advisories": {"GHSA-x": {"reason": "r"}}},
    ],
)
def test_the_previous_shape_does_not_loosen_validation(bad):
    with pytest.raises(ValueError):
        gate.load_allowlist_data(bad)


def test_a_bare_name_exemption_still_fails_closed_when_reachable_from_a_runtime_root():
    # The previous shape has no build_only_roots, so every production dependency
    # is a runtime root and a bare-name vite exemption cannot hold. It must
    # fail with a reason, not crash.
    allow = gate.load_allowlist(LEGACY_ALLOW)
    d = gate.decide(_vite_high_report(), allow, REAL_LOCK)
    assert not d.ok
    assert "reachable from the runtime dependency" in d.failures[0]


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
@pytest.mark.parametrize(
    "gate_kind,allow_kind",
    [("legacy", "legacy"), ("legacy", "current"), ("current", "legacy"), ("current", "current")],
)
def test_every_gate_and_allowlist_pairing_runs_without_a_crash(
    step, gate_kind, allow_kind, tmp_path
):
    g = LEGACY_GATE if gate_kind == "legacy" else _copy_gate(tmp_path)
    allow = LEGACY_ALLOW if allow_kind == "legacy" else ALLOWLIST
    r = _run_gate_step(step, g, allow, tmp_path, _report())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr


def test_the_pr_own_run_is_the_legacy_gate_on_the_legacy_allowlist_and_it_passes(tmp_path):
    # What web-audit does on this very PR: main's gate and allowlist, run by this
    # workflow. It must pass because the PR's audit is clean, not by crashing
    # on flags the old gate lacks.
    for step in ("Gate", "Gate (Worker, runtime)"):
        r = _run_gate_step(step, LEGACY_GATE, LEGACY_ALLOW, tmp_path, _report())
        assert r.returncode == 0, r.stdout + r.stderr
        assert "predates" in r.stdout


def test_the_legacy_gate_still_fails_a_runtime_high_through_the_workflow(tmp_path):
    report = _report(_vuln("preact", "high", "GHSA-pppp-0000-0000"))
    for step in ("Gate", "Gate (Worker, runtime)"):
        r = _run_gate_step(step, LEGACY_GATE, LEGACY_ALLOW, tmp_path, report)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "preact" in r.stdout


def test_the_legacy_gate_gets_no_exemptions_for_the_worker(tmp_path):
    # vite is exempt for the web app in the legacy allowlist, never for the Worker.
    web = _run_gate_step("Gate", LEGACY_GATE, LEGACY_ALLOW, tmp_path, _vite_high_report())
    worker = _run_gate_step("Gate (Worker, runtime)", LEGACY_GATE, LEGACY_ALLOW, tmp_path, _vite_high_report())
    assert web.returncode == 0, web.stdout
    assert worker.returncode == 1, worker.stdout


def test_the_legacy_gate_fails_closed_on_the_current_allowlist(tmp_path):
    # Not relied on (the base gate pairs with the base allowlist) but it must
    # fail with a message, not a traceback.
    r = _run_gate_step("Gate", LEGACY_GATE, ALLOWLIST, tmp_path, _vite_high_report())
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr


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
