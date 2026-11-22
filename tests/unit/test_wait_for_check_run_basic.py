"""``scripts/wait_for_check_run.py``: basic polling, pagination and CLI guards."""

from __future__ import annotations

import pytest

from tests.unit._wait_for_check_run_helpers import NAME, SHA, cr, mod, page, run

def test_in_progress_then_success_passes():
    ok, msg, calls = run([page(cr("in_progress")), page(cr("completed", "success"))])
    assert ok, msg
    cr_calls = [c for c in calls if "/check-runs" in c]
    assert len(cr_calls) == 2
    assert all(f"/commits/{SHA}/check-runs" in c for c in cr_calls)


def test_failure_conclusion_fails():
    ok, msg, _ = run([page(cr("completed", "failure"))])
    assert not ok and "failure" in msg and "no fallback run" in msg


@pytest.mark.parametrize("conclusion", ["cancelled", "neutral", "skipped", "timed_out", "action_required"])
def test_any_non_success_conclusion_fails(conclusion):
    ok, _, _ = run([page(cr("completed", conclusion))])
    assert not ok


def test_never_appearing_fails_on_timeout():
    ok, msg, _ = run([page()], timeout=30)
    assert not ok and "timed out" in msg and NAME in msg


def test_stuck_in_progress_fails_on_timeout():
    ok, msg, _ = run([page(cr("in_progress"))], timeout=30)
    assert not ok and "timed out" in msg


def test_wrong_name_only_fails():
    ok, _, _ = run([page(cr("completed", "success", name="Post-deploy URL verification"),
                         cr("completed", "success", name="Workers Builds: other"))], timeout=30)
    assert not ok


def test_name_match_is_exact():
    ok, _, _ = run([page(cr("completed", "success", name=NAME + " (preview)"))], timeout=30)
    assert not ok


def test_paginated_response_finds_run_on_later_page():
    first = {"total_count": 101, "check_runs": [cr("completed", "success", name=f"x{i}", id_=i) for i in range(100)]}
    second = {"total_count": 101, "check_runs": [cr("completed", "success", id_=500)]}
    ok, msg, calls = run([first, second])
    assert ok, msg
    assert any("page=2" in c for c in calls)


def test_rerun_uses_newest_run():
    old = cr("completed", "failure", id_=1)
    new = cr("completed", "success", id_=2)
    ok, _, _ = run([page(old, new)])
    assert ok


def test_api_error_is_retried_then_fails_at_timeout():
    def boom(url):
        raise OSError("down")

    now = [0.0]
    status, msg = mod.wait(boom, sha=SHA, name=NAME, timeout_secs=30, interval_secs=10,
                           sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert status == "fail" and "timed out" in msg


def test_main_requires_token(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    assert mod.main(["--sha", SHA]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_main_rejects_bad_sha(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    assert mod.main(["--sha", "main"]) == 2
