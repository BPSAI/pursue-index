"""The web dependency audit gate.

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
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "web_audit_gate.py"
ALLOWLIST = ROOT / "web" / "audit-build-only.json"
FIXTURES = ROOT / "tests" / "fixtures" / "web_audit"
WORKFLOW = ROOT / ".github" / "workflows" / "web-audit.yml"

sys.path.insert(0, str(ROOT / "scripts"))
import web_audit_gate as gate  # noqa: E402


def _advisory(name: str, severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict:
    return {
        "source": 1,
        "name": name,
        "dependency": name,
        "title": "t",
        "url": f"https://github.com/advisories/{ghsa}",
        "severity": severity,
        "range": "<1",
    }


def _report(*entries: dict) -> dict:
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {e["name"]: e for e in entries},
    }


def _vuln(name: str, severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict:
    return {
        "name": name,
        "severity": severity,
        "via": [_advisory(name, severity, ghsa)],
        "effects": [],
        "range": "<1",
        "nodes": [f"node_modules/{name}"],
        "fixAvailable": True,
    }


ALLOW = {
    "build_only": {"postcss": "bundled at build time, never shipped"},
    "accepted_advisories": {"GHSA-crit-0000-0000": "image optimisation is unused"},
}


def test_critical_fails():
    d = gate.decide(_report(_vuln("somepkg", "critical")), ALLOW)
    assert not d.ok
    assert any("somepkg" in f for f in d.failures)


def test_critical_in_build_only_package_still_fails():
    d = gate.decide(_report(_vuln("postcss", "critical")), ALLOW)
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
    assert not gate.decide(_report(v), ALLOW).ok


def test_runtime_high_fails():
    d = gate.decide(_report(_vuln("preact", "high")), ALLOW)
    assert not d.ok


def test_build_only_high_passes():
    d = gate.decide(_report(_vuln("postcss", "high")), ALLOW)
    assert d.ok
    assert d.build_only == ["postcss"]


def test_unknown_package_counts_as_runtime():
    d = gate.decide(_report(_vuln("brand-new-lib", "high")), {"build_only": {}})
    assert not d.ok


def test_moderate_and_low_do_not_fail():
    d = gate.decide(
        _report(_vuln("preact", "moderate"), _vuln("minisearch", "low")), ALLOW
    )
    assert d.ok


def test_transitive_entry_is_covered_by_its_source_package():
    # @astrojs/mdx is critical only because it depends on astro.
    mdx = {
        "name": "@astrojs/mdx",
        "severity": "critical",
        "via": ["astro"],
        "effects": [],
        "range": "*",
        "nodes": [],
        "fixAvailable": False,
    }
    astro = _vuln("astro", "critical", "GHSA-crit-0000-0000")
    assert gate.decide(_report(astro, mdx), ALLOW).ok
    # With the source unaccepted, the failure is reported on the source.
    bad = gate.decide(_report(_vuln("astro", "critical"), mdx), ALLOW)
    assert not bad.ok


def test_high_with_only_string_via_and_no_source_fails():
    orphan = {
        "name": "ghost",
        "severity": "high",
        "via": ["missing"],
        "effects": [],
        "range": "*",
        "nodes": [],
        "fixAvailable": False,
    }
    assert not gate.decide(_report(orphan), ALLOW).ok


def test_empty_report_passes():
    assert gate.decide({"auditReportVersion": 2, "vulnerabilities": {}}, ALLOW).ok


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"error": {"code": "ENOAUDIT", "summary": "registry unreachable"}},
        {"vulnerabilities": []},
        [],
        "x",
    ],
)
def test_malformed_or_errored_report_fails_closed(bad):
    d = gate.decide(bad, ALLOW)
    assert not d.ok


def test_allowlist_requires_a_reason_for_each_entry():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"x": ""}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"accepted_advisories": {"GHSA-x": "  "}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": ["x"]})


def test_recorded_report_before_upgrade_fails_without_allowlist():
    report = json.loads((FIXTURES / "audit_before.json").read_text())
    d = gate.decide(report, {"build_only": {}})
    assert not d.ok
    failing = " ".join(d.failures)
    assert "astro" in failing and "vite" in failing and "sharp" in failing


def test_committed_allowlist_passes_the_current_report():
    allow = gate.load_allowlist(ALLOWLIST)
    report = json.loads((FIXTURES / "audit_after.json").read_text())
    d = gate.decide(report, allow)
    assert d.ok, d.failures
    assert d.accepted == ["GHSA-26w7-cxv4-gfx2"]


def test_committed_allowlist_classifies_every_package_in_the_old_report():
    # Before the upgrade the only unclassified high advisories were astro's
    # own: astro is kept out of build_only on purpose, so new ones fail.
    allow = gate.load_allowlist(ALLOWLIST)
    report = json.loads((FIXTURES / "audit_before.json").read_text())
    d = gate.decide(report, allow)
    assert not d.ok
    assert all(f.startswith("astro:") for f in d.failures), d.failures


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report(_vuln("postcss", "high"))))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(_vuln("preact", "high"))))
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(ALLOW))

    def run(p):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), str(p), "--allowlist", str(allow)],
            capture_output=True,
            text=True,
        )

    assert run(good).returncode == 0
    r = run(bad)
    assert r.returncode == 1
    assert "preact" in r.stdout
    assert run(tmp_path / "missing.json").returncode == 1
    empty = tmp_path / "empty.json"
    empty.write_text("")
    assert run(empty).returncode == 1


def test_cli_reads_stdin(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(ALLOW))
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "-", "--allowlist", str(allow)],
        input=json.dumps(_report(_vuln("preact", "high"))),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1


# --- workflow shape -------------------------------------------------------


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # YAML 1.1 reads a bare `on:` key as boolean True.
    return data.get("on", data.get(True))


def test_workflow_runs_on_prs_touching_web_and_weekly():
    on = _on(_wf())
    pr = on["pull_request"]
    assert any(p.startswith("web/") for p in pr["paths"])
    assert any("web_audit_gate" in p for p in pr["paths"])
    crons = [s["cron"] for s in on["schedule"]]
    assert crons and all(len(c.split()) == 5 for c in crons)
    # The gate must not depend on the schedule alone.
    assert "pull_request" in on


def test_workflow_is_read_only_and_secretless():
    text = WORKFLOW.read_text(encoding="utf-8")
    data = _wf()
    assert data["permissions"] == {"contents": "read"}
    assert "${{ secrets" not in text
    assert "persist-credentials: false" in text


def test_workflow_check_name_is_stable():
    data = _wf()
    assert data["name"] == "web-audit"
    assert list(data["jobs"]) == ["audit"]
    assert data["jobs"]["audit"]["name"] == "web-audit"


def test_workflow_runs_the_gate_on_npm_audit_json():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "npm audit --omit=dev --json" in text
    assert "web_audit_gate.py" in text
