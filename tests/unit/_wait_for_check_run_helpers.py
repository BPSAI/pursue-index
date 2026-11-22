"""Shared fakes for the ``scripts/wait_for_check_run.py`` tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wait_for_check_run.py"
NAME = "Workers Builds: pursue-index"
SHA = "a" * 40
APP_ID = 85455  # the cloudflare-workers-and-pages GitHub App


def load():
    spec = importlib.util.spec_from_file_location("wait_for_check_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = load()


DEPLOY_STEP = "Deploy with wrangler"


def jobs_body(step_name, conclusion, *, job_conclusion="success"):
    """A run's jobs payload: one job whose steps include ``step_name``."""
    steps = [{"name": "Set up job", "status": "completed", "conclusion": "success"},
             {"name": step_name, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion}]
    return {"total_count": 1, "jobs": [{"id": 9, "conclusion": job_conclusion, "steps": steps}]}


def run(pages, *, timeout=60, name=NAME, fallback=None, compare=None, jobs=None):
    """Drive ``wait`` with scripted API responses and a fake clock.

    ``pages`` script the check-runs endpoint, ``fallback`` the deploy-cf
    workflow-runs endpoint, ``compare`` the compare endpoint, ``jobs`` the fallback run's jobs endpoint
    (default: the deploy step succeeded; items may be Exceptions).
    """
    calls = []
    queue = list(pages)
    fb = list(fallback or [{"total_count": 0, "workflow_runs": []}])  # items may be Exceptions
    cmp_ = compare or {"ahead_by": 0, "behind_by": 0}
    jb = list(jobs or [jobs_body(DEPLOY_STEP, "success")])

    def fetch(url):
        calls.append(url)
        if "/actions/workflows/" in url:
            item = fb.pop(0) if len(fb) > 1 else fb[0]
            if isinstance(item, Exception):
                raise item
            return item
        if "/jobs" in url:
            item = jb.pop(0) if len(jb) > 1 else jb[0]
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
