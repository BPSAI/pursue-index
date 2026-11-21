"""Accepted advisories, their review_by dates, and the allowlist reader.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys

import pytest

from tests.support.web_audit_support import (
    ALLOW,
    ALLOWLIST,
    FIXTURES,
    LOCK,
    REAL_LOCK,
    SCRIPT,
    TODAY,
    _report,
    _vuln,
    gate,
)

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


def test_a_bare_string_acceptance_loads_only_as_the_previous_shape():
    allow = gate.load_allowlist_data({"accepted_advisories": {"GHSA-x": "just a reason"}})
    assert allow["legacy"] == ["accepted_advisories['GHSA-x'] has no review_by date"]


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
