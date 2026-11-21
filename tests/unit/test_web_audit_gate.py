"""The web dependency audit gate: critical, runtime and build-only verdicts.

``scripts/web_audit_gate.py`` reads ``npm audit --omit=dev --json`` output and
fails on any unaccepted critical advisory, and on any high advisory in a
package that is not listed as build-only. A package missing from the
allowlist counts as runtime.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.web_audit_support import (
    ALLOW,
    ALLOWLIST,
    LOCK,
    ROOT,
    SCRIPT,
    TODAY,
    WEB_LOCK,
    _advisory,
    _lock,
    _report,
    _vuln,
    _wf,
    gate,
)


def test_critical_fails():
    d = gate.decide(_report(_vuln("somepkg", "critical")), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok
    assert any("somepkg" in f for f in d.failures)


def test_critical_in_build_only_package_still_fails():
    d = gate.decide(_report(_vuln("postcss", "critical")), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok


def test_accepted_critical_advisory_passes():
    d = gate.decide(
        _report(_vuln("astro", "critical", "GHSA-crit-0000-0000")), ALLOW
    )
    assert d.ok
    assert d.accepted


def test_one_unaccepted_critical_among_accepted_fails():
    v = _vuln("astro", "critical", "GHSA-crit-0000-0000")
    v["via"].append(_advisory("astro", "critical", "GHSA-new0-0000-0000"))
    assert not gate.decide(_report(v), ALLOW, lock=LOCK, today=TODAY).ok


def test_runtime_high_fails():
    d = gate.decide(_report(_vuln("preact", "high")), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok


def test_build_only_high_passes():
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=LOCK, today=TODAY)
    assert d.ok
    assert d.build_only == ["postcss"]


# --- build-only exemptions match exact name@version pairs from the lockfile.


def test_build_only_matches_the_exact_installed_version():
    lock = _lock(postcss="8.5.0")
    assert gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=lock, today=TODAY).ok


def test_build_only_does_not_cover_another_version_of_the_name():
    lock = _lock(postcss="8.6.0")
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=lock, today=TODAY)
    assert not d.ok
    assert any("postcss@8.6.0" in f for f in d.failures)


def test_every_installed_copy_must_be_exempted():
    lock = _lock(postcss="8.5.0")
    lock["packages"]["node_modules/vite/node_modules/postcss"] = {"version": "8.4.0"}
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=lock, today=TODAY)
    assert not d.ok
    assert any("postcss@8.4.0" in f for f in d.failures)


def test_dev_only_copies_do_not_count():
    lock = _lock(postcss="8.5.0")
    lock["packages"]["node_modules/vite/node_modules/postcss"] = {"version": "8.4.0", "dev": True}
    assert gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=lock, today=TODAY).ok


def test_without_a_lockfile_nothing_is_exempt():
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=None, today=TODAY)
    assert not d.ok


def test_package_absent_from_the_lockfile_is_not_exempt():
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW, lock=_lock(), today=TODAY)
    assert not d.ok


def test_a_bare_name_build_only_key_loads_only_as_the_previous_shape():
    allow = gate.load_allowlist_data({"build_only": {"postcss": "reason"}})
    assert any("'postcss'] is a bare package name" in n for n in allow["legacy"])
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"postcss@": "reason"}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"@scope/pkg/x": "reason"}})
    assert gate.load_allowlist_data({"build_only": {"@scope/pkg@1.2.3": "reason"}})["legacy"] == []



# --- the Worker is runtime: any high or critical fails, nothing is exempt.


def test_runtime_mode_fails_any_high_even_if_it_is_listed_build_only():
    d = gate.decide_runtime(_report(_vuln("postcss", "high")))
    assert not d.ok
    assert any("postcss" in f for f in d.failures)


def test_runtime_mode_fails_a_critical():
    assert not gate.decide_runtime(_report(_vuln("x", "critical", "GHSA-crit-0000-0000"))).ok


def test_runtime_mode_ignores_moderate_and_low():
    assert gate.decide_runtime(_report(_vuln("x", "moderate"), _vuln("y", "low"))).ok


def test_runtime_mode_fails_closed_on_unknown_severity():
    entry = _vuln("x", "low")
    entry["severity"] = "bogus"
    assert not gate.decide_runtime(_report(entry)).ok


def test_runtime_mode_passes_a_clean_report():
    assert gate.decide_runtime(_report()).ok


def test_runtime_mode_rejects_a_transitive_only_high():
    # A high that appears only as "via another package" still fails here.
    v = {"name": "wrapper", "severity": "high", "via": ["inner"], "nodes": [], "range": "*"}
    assert not gate.decide_runtime(_report(v, _vuln("inner", "high"))).ok


def test_cli_runtime_mode(tmp_path):
    def run(body):
        f = tmp_path / "w.json"
        f.write_text(json.dumps(body))
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), str(f), "--runtime"],
            capture_output=True, text=True,
        )

    assert run(_report()).returncode == 0
    r = run(_report(_vuln("postcss", "high")))
    assert r.returncode == 1 and "postcss" in r.stdout
    assert run({"error": {}}).returncode == 2


def test_workflow_audits_the_worker_with_the_runtime_gate():
    steps = [st for st in _wf()["jobs"]["audit"]["steps"] if "run" in st]
    worker = [st for st in steps if st.get("working-directory") == "worker"]
    assert worker and "npm audit --omit=dev --json" in worker[0]["run"]
    assert any("--runtime" in st["run"] and "worker-audit.json" in st["run"] for st in steps)
    # No exemptions: the runtime step never takes the build-only allowlist. Only
    # a gate that predates --runtime gets an allowlist, and that one is empty.
    runtime_step = next(st for st in steps if "--runtime" in st["run"])
    run = runtime_step["run"]
    assert "ALLOWLIST" not in run and "audit-build-only" not in run
    assert "--runtime" in run.split("else")[0] and "--allowlist" not in run.split("else")[0]
    assert "echo '{}'" in run


def test_the_worker_has_a_lockfile_for_the_audit():
    assert (ROOT / "worker" / "package-lock.json").is_file()



# --- An unusable audit report is rejected (exit 2), never read as zero findings.
# The workflow runs `npm audit ... || true`, so an npm or registry error still
# produces a file; the gate must refuse it rather than pass.

def _cli(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    f = tmp_path / "audit.json"
    f.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(f), "--allowlist", str(ALLOWLIST),
         "--lockfile", str(WEB_LOCK)],
        capture_output=True, text=True, check=False,
    )


def test_a_report_with_an_error_key_is_rejected(tmp_path: Path) -> None:
    body = {"error": {"code": "ENOTFOUND", "summary": "registry unreachable"}}
    r = _cli(tmp_path, json.dumps(body))
    assert r.returncode == 2, r.stdout
    assert "error" in r.stdout


def test_an_empty_error_key_is_still_rejected(tmp_path: Path) -> None:
    body = {**_report(), "error": {}}
    r = _cli(tmp_path, json.dumps(body))
    assert r.returncode == 2, r.stdout


def test_a_report_without_metadata_vulnerabilities_is_rejected(tmp_path: Path) -> None:
    body = {"auditReportVersion": 2, "vulnerabilities": {}}
    r = _cli(tmp_path, json.dumps(body))
    assert r.returncode == 2, r.stdout
    assert "metadata.vulnerabilities" in r.stdout


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    r = _cli(tmp_path, "npm ERR! network request failed\n")
    assert r.returncode == 2, r.stdout


def test_a_clean_well_formed_report_still_passes(tmp_path: Path) -> None:
    r = _cli(tmp_path, json.dumps(_report()))
    assert r.returncode == 0, r.stdout
