"""``scripts/wait_for_check_run.py``: the manual deploy-cf fallback."""

from __future__ import annotations

from tests.unit._wait_for_check_run_helpers import DEPLOY_STEP, SHA, cr, jobs_body, page, run, wf

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


# ---- the fallback counts only when its deploy step succeeded ---------------

def test_fallback_success_with_skipped_deploy_step_is_not_accepted():
    ok, msg, calls = run([page()], timeout=30, fallback=[wf("completed", "success", id_=7)],
                         jobs=[jobs_body(DEPLOY_STEP, "skipped")])
    assert not ok and run.status == "fail"
    assert any("/actions/runs/7/jobs" in c for c in calls)
    assert "deploy step" in msg


def test_fallback_success_with_failed_deploy_step_but_green_job_is_not_accepted():
    # the deploy step is continue-on-error, so the job and run read green
    ok, _, _ = run([page()], timeout=30, fallback=[wf("completed", "success")],
                   jobs=[jobs_body(DEPLOY_STEP, "failure")])
    assert not ok


def test_fallback_success_without_a_deploy_step_is_not_accepted():
    ok, _, _ = run([page()], timeout=30, fallback=[wf("completed", "success")],
                   jobs=[jobs_body("Some other step", "success")])
    assert not ok


def test_fallback_success_with_successful_deploy_step_is_accepted():
    ok, msg, calls = run([page()], fallback=[wf("completed", "success", id_=7)],
                         jobs=[jobs_body(DEPLOY_STEP, "success")])
    assert ok and run.status == "ok", msg
    assert any("/actions/runs/7/jobs" in c for c in calls)


def test_fallback_jobs_lookup_error_is_unknown_then_retried():
    ok, _, _ = run([page()], fallback=[wf("completed", "success")],
                   jobs=[OSError("500"), jobs_body(DEPLOY_STEP, "success")])
    assert ok and run.status == "ok"


def test_fallback_jobs_lookup_error_until_timeout_fails_unknown():
    ok, msg, _ = run([page()], timeout=30, fallback=[wf("completed", "success")], jobs=[OSError("500")])
    assert not ok and "unknown" in msg


def test_older_fallback_run_with_deployed_step_is_accepted_when_newest_skipped():
    fb = {"total_count": 2, "workflow_runs": [
        {"id": 1, "status": "completed", "conclusion": "success"},
        {"id": 2, "status": "completed", "conclusion": "success"}]}
    ok, _, _ = run([page()], fallback=[fb],
                   jobs=[jobs_body(DEPLOY_STEP, "skipped"), jobs_body(DEPLOY_STEP, "success")])
    assert ok


# ---- a terminal deploy-step verdict is read once -----------------------------

def _jobs_reads(calls, run_id):
    return [c for c in calls if f"/actions/runs/{run_id}/jobs" in c]


def test_terminal_failed_verdict_is_read_once_across_polls():
    ok, _, calls = run([page()], timeout=60, fallback=[wf("completed", "success", id_=7)],
                       jobs=[jobs_body(DEPLOY_STEP, "failure")])
    assert not ok
    assert len(_jobs_reads(calls, 7)) == 1


def test_terminal_skipped_verdict_is_read_once_across_polls():
    ok, _, calls = run([page()], timeout=60, fallback=[wf("completed", "success", id_=7)],
                       jobs=[jobs_body(DEPLOY_STEP, "skipped")])
    assert not ok
    assert len(_jobs_reads(calls, 7)) == 1


def test_unknown_verdict_is_reread_until_terminal():
    # the deploy step is still running on the first read, then succeeds
    ok, msg, calls = run([page()], timeout=60, fallback=[wf("completed", "success", id_=7)],
                         jobs=[jobs_body(DEPLOY_STEP, None), jobs_body(DEPLOY_STEP, None),
                               jobs_body(DEPLOY_STEP, "success")])
    assert ok, msg
    assert len(_jobs_reads(calls, 7)) == 3


def test_a_failed_older_run_is_not_reread_while_a_newer_run_is_unknown():
    fb = {"total_count": 2, "workflow_runs": [
        {"id": 1, "status": "completed", "conclusion": "success"},
        {"id": 2, "status": "completed", "conclusion": "success"}]}

    ok, _, calls = run([page()], timeout=40, fallback=[fb],
                       jobs=[jobs_body(DEPLOY_STEP, None), jobs_body(DEPLOY_STEP, "failure")])
    assert not ok
    assert len(_jobs_reads(calls, 1)) == 1
