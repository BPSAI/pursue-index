"""``scripts/wait_for_check_run.py``: the manual deploy-cf fallback."""

from __future__ import annotations

from tests.unit._wait_for_check_run_helpers import SHA, cr, page, run, wf

# ---- fallback deploy (deploy-cf.yml) -------------------------------------

def test_workers_builds_success_passes_without_fallback():
    ok, msg, _ = run([page(cr("completed", "success"))])
    assert ok and run.status == "ok"


def test_fallback_success_passes_when_no_workers_builds_run():
    ok, msg, calls = run([page()], fallback=[wf("completed", "success")])
    assert ok, msg
    assert any(f"/actions/workflows/deploy-cf.yml/runs?head_sha={SHA}" in c for c in calls)


def test_fallback_success_passes_after_workers_builds_failure():
    ok, msg, _ = run([page(cr("completed", "failure"))], fallback=[wf("completed", "success")])
    assert ok, msg


def test_fallback_in_progress_then_success():
    ok, _, _ = run([page()], fallback=[wf("in_progress"), wf("completed", "success")])
    assert ok


def test_both_absent_fails_at_timeout_naming_both():
    ok, msg, _ = run([page()], timeout=30)
    assert not ok and run.status == "fail"
    assert "timed out" in msg and "no fallback run" in msg and "no check run" in msg


def test_workers_builds_failure_and_fallback_failure_reports_both():
    ok, msg, _ = run([page(cr("completed", "failure"))], timeout=30, fallback=[wf("completed", "failure")])
    assert not ok and "failure" in msg


# ---- fallback lookup errors never override a successful build ------------

def test_workers_builds_success_with_fallback_api_erroring_passes():
    ok, msg, calls = run([page(cr("completed", "success"))], fallback=[OSError("500")])
    assert ok and run.status == "ok", msg
    assert not any("/actions/workflows/" in c for c in calls)  # not consulted on success


def test_workers_builds_failure_then_fallback_error_then_success_passes():
    ok, msg, _ = run([page(cr("completed", "failure"))], fallback=[OSError("500"), wf("completed", "success")])
    assert ok and run.status == "ok", msg


def test_workers_builds_failure_and_fallback_erroring_until_timeout_fails_unknown():
    ok, msg, _ = run([page(cr("completed", "failure"))], timeout=30, fallback=[OSError("500")])
    assert not ok and run.status == "fail"
    assert "fallback status unknown" in msg


def test_fallback_not_consulted_while_build_in_progress():
    _, _, calls = run([page(cr("in_progress")), page(cr("completed", "success"))])
    assert not any("/actions/workflows/" in c for c in calls)
