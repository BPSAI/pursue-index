"""The web dependency audit gate.

``scripts/web_audit_gate.py`` reads ``npm audit --omit=dev --json`` output and
fails on any unaccepted critical advisory, and on any high advisory in a
package that is not listed as build-only. A package missing from the
allowlist counts as runtime.
"""

from __future__ import annotations

import datetime
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
WEB_LOCK = ROOT / "web" / "package-lock.json"
REAL_LOCK = json.loads(WEB_LOCK.read_text(encoding="utf-8"))
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
    counts = {k: 0 for k in ("info", "low", "moderate", "high", "critical")}
    for e in entries:
        counts[e["severity"]] = counts.get(e["severity"], 0) + 1
    counts["total"] = len(entries)
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {e["name"]: e for e in entries},
        "metadata": {"vulnerabilities": counts},
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


TODAY = datetime.date(2026, 11, 21)

def _lock(**versions: str) -> dict:
    """A minimal package-lock.json: one top-level install per name."""
    pkgs: dict[str, dict] = {"": {"name": "web", "version": "0.0.1"}}
    for name, version in versions.items():
        pkgs[f"node_modules/{name}"] = {"version": version}
    return {"lockfileVersion": 3, "packages": pkgs}


LOCK = _lock(postcss="8.5.0", preact="10.0.0", astro="7.0.0", somepkg="1.0.0")

def _graph_lock(roots: dict, pkgs: dict) -> dict:
    """A lockfile with a dependency graph.

    ``roots`` maps the project's production dependencies to a version;
    ``pkgs`` maps a lock path (``node_modules/x``) to ``(version, deps)`` where
    ``deps`` is a list of names, or a dict with ``dependencies``,
    ``optionalDependencies`` and ``peerDependencies`` lists.
    """
    packages: dict[str, dict] = {
        "": {"name": "web", "version": "0.0.1", "dependencies": {r: "*" for r in roots}}
    }
    for key, (version, deps) in pkgs.items():
        meta: dict = {"version": version}
        kinds = deps if isinstance(deps, dict) else {"dependencies": deps}
        for kind, names in kinds.items():
            meta[kind] = {n: "*" for n in names}
        packages[key] = meta
    for r, v in roots.items():
        packages.setdefault(f"node_modules/{r}", {"version": v})
    return {"lockfileVersion": 3, "packages": packages}


ROOTS_ALLOW = {
    "build_only": {"postcss@8.5.0": "build time", "nanoid@3.0.0": "build time"},
    "build_only_roots": {"astro": "the site generator runs only at build time"},
    "accepted_advisories": {},
}


def _pc(*extra: tuple[str, tuple]) -> dict:
    """astro (build-only root) -> postcss; plus whatever ``extra`` adds."""
    pkgs = {
        "node_modules/astro": ("7.0.0", ["postcss"]),
        "node_modules/postcss": ("8.5.0", ["nanoid"]),
        "node_modules/nanoid": ("3.0.0", []),
        "node_modules/preact": ("10.0.0", []),
    }
    pkgs.update(dict(extra))
    return _graph_lock({"astro": "7.0.0", "preact": "10.0.0"}, pkgs)


ALLOW = {
    "build_only": {"postcss@8.5.0": "bundled at build time, never shipped"},
    "accepted_advisories": {
        "GHSA-crit-0000-0000": {
            "reason": "image optimisation is unused",
            "review_by": "2099-12-31",
        }
    },
}


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


def test_a_bare_name_is_not_a_valid_build_only_key():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"postcss": "reason"}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"postcss@": "reason"}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"@scope/pkg": "reason"}})
    gate.load_allowlist_data({"build_only": {"@scope/pkg@1.2.3": "reason"}})


# --- a transitive skip needs EVERY path to come from a build-only root.


def _roots_decide(lock, pkg="postcss"):
    return gate.decide(_report(_vuln(pkg, "high")), ROOTS_ALLOW, lock=lock, today=TODAY)


def test_reached_only_from_a_build_only_root_is_exempt():
    assert _roots_decide(_pc()).ok


def test_a_runtime_root_reaching_it_directly_makes_it_runtime():
    lock = _pc(("node_modules/preact", ("10.0.0", ["postcss"])))
    d = _roots_decide(lock)
    assert not d.ok
    assert any("preact" in f and "runtime" in f for f in d.failures)


def test_a_deep_transitive_runtime_path_makes_it_runtime():
    lock = _pc(
        ("node_modules/preact", ("10.0.0", ["a"])),
        ("node_modules/a", ("1.0.0", ["b"])),
        ("node_modules/b", ("1.0.0", ["postcss"])),
    )
    assert not _roots_decide(lock).ok


def test_a_runtime_path_to_a_transitive_of_the_exempt_package_is_caught():
    # nanoid is exempt, but preact -> nanoid is a runtime path to it.
    lock = _pc(("node_modules/preact", ("10.0.0", ["nanoid"])))
    assert not _roots_decide(lock, pkg="nanoid").ok


def test_optional_and_peer_edges_count_as_paths():
    for kind in ("optionalDependencies", "peerDependencies"):
        lock = _pc(("node_modules/preact", ("10.0.0", {kind: ["postcss"]})))
        assert not _roots_decide(lock).ok, kind


def test_a_runtime_root_that_is_itself_the_package_is_runtime():
    allow = {**ROOTS_ALLOW, "build_only": {"preact@10.0.0": "wrongly listed"}}
    d = gate.decide(_report(_vuln("preact", "high")), allow, lock=_pc(), today=TODAY)
    assert not d.ok


def test_a_nested_copy_is_resolved_the_way_node_does():
    # preact's own nested postcss shadows the top-level one for preact only.
    nested = ("node_modules/preact/node_modules/postcss", ("8.5.0", []))
    on_runtime = _pc(("node_modules/preact", ("10.0.0", ["postcss"])), nested)
    assert not _roots_decide(on_runtime).ok
    # With no edge from preact, the nested copy is not reachable from it.
    off_runtime = _pc(nested)
    assert _roots_decide(off_runtime).ok


def test_without_build_only_roots_nothing_is_exempt():
    allow = {**ROOTS_ALLOW}
    allow.pop("build_only_roots")
    d = gate.decide(_report(_vuln("postcss", "high")), allow, lock=_pc(), today=TODAY)
    assert not d.ok


def test_a_root_that_depends_on_a_package_by_a_missing_lock_entry_is_ignored():
    lock = _pc(("node_modules/preact", ("10.0.0", ["not-installed"])))
    assert _roots_decide(lock).ok


def test_build_only_roots_need_reasons():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only_roots": {"astro": ""}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only_roots": ["astro"]})


def test_committed_exemptions_are_not_reachable_from_a_runtime_root():
    allow = gate.load_allowlist(ALLOWLIST)
    assert allow["build_only_roots"], "the committed allowlist must name its build-only roots"
    runtime = gate.runtime_roots(REAL_LOCK, allow["build_only_roots"])
    assert {"preact", "minisearch", "regl-scatterplot", "@preact/signals"} <= set(runtime)
    for key in allow["build_only"]:
        name = key.rsplit("@", 1)[0]
        assert gate.not_build_only(name, allow, REAL_LOCK) is None, key


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
    assert gate.decide(_report(astro, mdx), ALLOW, lock=LOCK, today=TODAY).ok
    # With the source unaccepted, the failure is reported on the source.
    bad = gate.decide(_report(_vuln("astro", "critical"), mdx), ALLOW, lock=LOCK, today=TODAY)
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
    assert not gate.decide(_report(orphan), ALLOW, lock=LOCK, today=TODAY).ok


@pytest.mark.parametrize("sev", ["none", "severe", "HIGH", "", None, 3])
def test_unknown_severity_fails_closed(sev):
    entry = _vuln("preact", "low")
    entry["severity"] = sev
    d = gate.decide(_report(entry), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok
    assert any("severity" in f for f in d.failures)


def test_unknown_severity_on_an_advisory_fails_closed():
    entry = _vuln("preact", "low")
    entry["via"][0]["severity"] = "catastrophic"
    d = gate.decide(_report(entry), ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok


@pytest.mark.parametrize("sev", ["info", "low", "moderate", "high", "critical"])
def test_every_documented_severity_is_understood(sev):
    d = gate.decide(_report(_vuln("postcss", sev)), ALLOW, lock=LOCK, today=TODAY)
    assert not any("severity" in f for f in d.failures)


# --- review_by: an accepted advisory is re-reviewed by a date, against a fixed clock.


def _accepting(review_by: object) -> dict:
    return {
        "build_only": {},
        "accepted_advisories": {
            "GHSA-crit-0000-0000": {"reason": "unused path", "review_by": review_by}
        },
    }


def _accepted_report() -> dict:
    return _report(_vuln("astro", "critical", "GHSA-crit-0000-0000"))


def test_accepted_advisory_passes_before_and_on_its_review_date():
    allow = _accepting("2026-11-21")
    assert gate.decide(_accepted_report(), allow, today=datetime.date(2026, 11, 20)).ok
    assert gate.decide(_accepted_report(), allow, today=datetime.date(2026, 11, 21)).ok


def test_accepted_advisory_fails_the_day_after_its_review_date():
    d = gate.decide(_accepted_report(), _accepting("2026-11-21"), today=datetime.date(2026, 11, 22))
    assert not d.ok
    assert any("GHSA-crit-0000-0000" in f and "review_by" in f for f in d.failures)


def test_an_expired_acceptance_fails_even_when_the_advisory_is_absent():
    d = gate.decide(_report(), _accepting("2026-01-01"), today=TODAY)
    assert not d.ok


@pytest.mark.parametrize("bad", [None, "", "soon", "2026-13-01", "21-11-2026", 20261121])
def test_allowlist_rejects_a_missing_or_malformed_review_by(bad):
    with pytest.raises(ValueError):
        gate.load_allowlist_data(_accepting(bad))
    entry = {"reason": "unused path"}
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"accepted_advisories": {"GHSA-x": entry}})


def test_a_bare_string_acceptance_is_rejected():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"accepted_advisories": {"GHSA-x": "just a reason"}})


def test_empty_report_passes():
    assert gate.decide({"auditReportVersion": 2, "vulnerabilities": {}}, ALLOW, lock=LOCK, today=TODAY).ok


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
    d = gate.decide(bad, ALLOW, lock=LOCK, today=TODAY)
    assert not d.ok


def test_allowlist_requires_a_reason_for_each_entry():
    with pytest.raises(ValueError):
        gate.load_allowlist_data({"build_only": {"x": ""}})
    with pytest.raises(ValueError):
        gate.load_allowlist_data(
            {"accepted_advisories": {"GHSA-x": {"reason": "  ", "review_by": "2027-01-01"}}}
        )
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
    report = json.loads((FIXTURES / "audit_astro7.json").read_text())
    d = gate.decide(report, allow, lock=REAL_LOCK, today=TODAY)
    assert d.ok, d.failures
    assert d.accepted == []


def test_the_avif_advisory_is_no_longer_accepted():
    # astro 7 fixes GHSA-26w7-cxv4-gfx2, so the acceptance is gone: the same
    # advisory reappearing (a downgrade) must fail the gate.
    allow = gate.load_allowlist(ALLOWLIST)
    assert "GHSA-26w7-cxv4-gfx2" not in allow["accepted_advisories"]
    report = json.loads((FIXTURES / "audit_after.json").read_text())
    d = gate.decide(report, allow, lock=REAL_LOCK, today=TODAY)
    assert not d.ok
    assert any("GHSA-26w7-cxv4-gfx2" in f for f in d.failures)


def test_cli_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_report(_vuln("postcss", "high"))))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_report(_vuln("preact", "high"))))
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(ALLOW))
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(LOCK))

    def run(p):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), str(p), "--allowlist", str(allow),
             "--lockfile", str(lock)],
            capture_output=True,
            text=True,
        )

    assert run(good).returncode == 0
    r = run(bad)
    assert r.returncode == 1
    assert "preact" in r.stdout
    # An unreadable report is unusable, like invalid JSON: exit 2, never a pass.
    assert run(tmp_path / "missing.json").returncode == 2
    empty = tmp_path / "empty.json"
    empty.write_text("")
    assert run(empty).returncode == 2


def test_cli_fails_when_the_lockfile_is_unreadable(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(ALLOW))
    rep = tmp_path / "rep.json"
    rep.write_text(json.dumps(_report()))
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(rep), "--allowlist", str(allow),
         "--lockfile", str(tmp_path / "nope.json")],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "lockfile" in r.stdout


def test_cli_reads_stdin(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps(ALLOW))
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps(LOCK))
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "-", "--allowlist", str(allow),
         "--lockfile", str(lock)],
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
