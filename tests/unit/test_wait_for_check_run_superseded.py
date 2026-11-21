"""``scripts/wait_for_check_run.py``: superseded builds."""

from __future__ import annotations

import pytest

from tests.unit._wait_for_check_run_helpers import SCRIPT, SHA, cr, load, mod, page, run, wf

# ---- superseded builds ---------------------------------------------------

AHEAD = {"ahead_by": 2, "behind_by": 0}


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped"])
def test_cancelled_or_skipped_with_main_ahead_is_superseded(conclusion):
    ok, msg, calls = run([page(cr("completed", conclusion))], compare=AHEAD)
    assert run.status == "superseded" and "superseded" in msg
    assert any(f"/compare/{SHA}...main" in c for c in calls)


def test_no_check_run_yet_with_main_ahead_keeps_waiting_not_superseded():
    ok, msg, _ = run([page(), page(), page(cr("completed", "success"))], compare=AHEAD)
    assert ok and run.status == "ok", msg


def test_no_check_run_ever_with_main_ahead_is_a_timeout_failure():
    ok, msg, calls = run([page()], timeout=30, compare=AHEAD)
    assert not ok and run.status == "fail" and "timed out" in msg
    assert not any("/compare/" in c for c in calls)


def test_no_check_run_ever_main_ahead_still_passes_on_fallback_success():
    ok, _, _ = run([page()], compare=AHEAD, fallback=[wf("completed", "success")])
    assert ok and run.status == "ok"


def test_failure_with_main_ahead_is_not_superseded():
    ok, _, _ = run([page(cr("completed", "failure"))], timeout=30, compare=AHEAD)
    assert not ok and run.status == "fail"


def test_cancelled_with_main_not_ahead_fails():
    ok, _, _ = run([page(cr("completed", "cancelled"))], timeout=30)
    assert not ok and run.status == "fail"


def test_diverged_main_is_not_superseded():
    run([page(cr("completed", "cancelled"))], timeout=30, compare={"ahead_by": 2, "behind_by": 1})
    assert run.status == "fail"


def test_main_writes_superseded_output(monkeypatch, tmp_path, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(mod, "_fetcher", lambda t: (lambda url: {"ahead_by": 1, "behind_by": 0} if "/compare/" in url
                                                    else {"total_count": 1, "check_runs": [cr("completed", "cancelled")],
                                                          "workflow_runs": []}))
    assert mod.main(["--sha", SHA, "--timeout-secs", "5"]) == 0
    assert "superseded=true" in out.read_text()
    assert "::notice" in capsys.readouterr().out


def test_check_name_default_is_single_constant_and_env_overridable(monkeypatch):
    src = SCRIPT.read_text()
    assert src.count("Workers Builds: pursue-index") == 1
    monkeypatch.setenv("WORKERS_BUILD_CHECK_NAME", "Other")
    assert load().default_name() == "Other"
