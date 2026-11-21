"""``scripts/wait_for_check_run.py``: wait for one commit's build check run."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wait_for_check_run.py"
NAME = "Workers Builds: pursue-index"
SHA = "a" * 40
APP_ID = 85455  # the cloudflare-workers-and-pages GitHub App


def _load():
    spec = importlib.util.spec_from_file_location("wait_for_check_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def run(pages, *, timeout=60, name=NAME, fallback=None, compare=None):
    """Drive ``wait`` with scripted API responses and a fake clock.

    ``pages`` script the check-runs endpoint, ``fallback`` the deploy-cf
    workflow-runs endpoint, ``compare`` the compare endpoint.
    """
    calls = []
    queue = list(pages)
    fb = list(fallback or [{"total_count": 0, "workflow_runs": []}])  # items may be Exceptions
    cmp_ = compare or {"ahead_by": 0, "behind_by": 0}

    def fetch(url):
        calls.append(url)
        if "/actions/workflows/" in url:
            item = fb.pop(0) if len(fb) > 1 else fb[0]
            if isinstance(item, Exception):
                raise item
            return item
        if "/compare/" in url:
            return cmp_
        return queue.pop(0) if len(queue) > 1 else queue[0]

    now = [0.0]

    def sleep(s):
        now[0] += s

    status, msg = mod.wait(fetch, sha=SHA, name=name, timeout_secs=timeout,
                           interval_secs=10, sleep=sleep, clock=lambda: now[0])
    run.status = status
    return status == "ok", msg, calls


def wf(status, conclusion=None, id_=1):
    return {"total_count": 1, "workflow_runs": [{"id": id_, "status": status, "conclusion": conclusion}]}


def cr(status, conclusion=None, name=NAME, id_=1, app_id=APP_ID):
    return {"id": id_, "name": name, "status": status, "conclusion": conclusion, "app": {"id": app_id}}


def page(*runs, total=None):
    return {"total_count": total if total is not None else len(runs), "check_runs": list(runs)}


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
    assert _load().default_name() == "Other"


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


# ---- matching by app id and name -----------------------------------------

def test_same_name_run_from_another_app_is_ignored():
    ok, _, _ = run([page(cr("completed", "success", app_id=15368))], timeout=30)
    assert not ok and run.status == "fail"


def test_run_without_app_is_ignored():
    bare = {"id": 1, "name": NAME, "status": "completed", "conclusion": "success"}
    ok, _, _ = run([page(bare)], timeout=30)
    assert not ok


def test_app_id_default_is_single_constant_and_env_overridable(monkeypatch):
    assert SCRIPT.read_text().count("85455") == 1
    monkeypatch.setenv("WORKERS_BUILD_APP_ID", "7")
    assert _load().default_app_id() == 7
