"""Shape of ``verify-assets-weekly.yml``: weekly schedule, dispatch, a budgeted full hash."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/verify-assets-weekly.yml"


def _data() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict]:
    return [s for job in _data()["jobs"].values() for s in job["steps"]]


def _hash_step() -> dict:
    return next(s for s in _steps() if "--full-hash" in (s.get("run") or ""))


def test_weekly_schedule_and_manual_dispatch():
    on = _data()[True]  # PyYAML parses the bare key `on` as True
    assert "workflow_dispatch" in on
    crons = [e["cron"] for e in on["schedule"]]
    assert len(crons) == 1
    minute, hour, dom, month, dow = crons[0].split()
    assert dom == "*" and month == "*" and dow.isdigit(), "a weekly cron names one weekday"


def test_runs_full_hash_with_a_byte_budget():
    run = _hash_step()["run"]
    assert "scripts/r2_archive_assets.py" in run
    assert "--max-bytes-per-run" in run


def test_hashing_step_does_not_swallow_failures():
    step = _hash_step()
    assert "continue-on-error" not in step or step["continue-on-error"] is False


def test_shares_the_registry_writer_lock():
    assert _data()["concurrency"]["group"] == "pursue-registry-writers"


def test_job_has_a_timeout_that_covers_a_full_hash():
    job = next(iter(_data()["jobs"].values()))
    assert job["timeout-minutes"] >= 120


def test_run_record_is_committed_to_the_rolling_branch():
    text = WORKFLOW.read_text()
    assert "full-hash-runs.jsonl" in text
    assert "verify/registry" in text
