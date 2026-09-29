"""Workflow wiring for the stale-edge guard (#157).

The poll script now reports ``stale``, ``pending`` and ``benign`` as well as
``unchanged``/``changed``/``failed``. Pin how ``poll-pursue.yml`` treats
each: only ``changed`` opens an issue or runs the snapshot lane; the guard
state is committed by the same step that commits the sha; ``stale`` commits
nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "poll-pursue.yml"


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["poll"]["steps"]


def _step(name_part: str) -> dict:
    matches = [s for s in _steps() if name_part in str(s.get("name", ""))]
    assert len(matches) == 1, f"expected one step named like {name_part!r}"
    return matches[0]


def test_sha_commit_step_also_commits_guard_state_and_covers_benign() -> None:
    step = _step("Commit new sha")
    assert "data/poll-state.json" in step["run"]
    cond = str(step["if"])
    assert "'changed'" in cond and "'benign'" in cond
    assert "stale" not in cond


def test_backfill_step_persists_pending_guard_state_but_not_stale() -> None:
    step = _step("Archive CSV bytes on every poll")
    assert "data/poll-state.json" in step["run"]
    cond = str(step["if"])
    assert "'unchanged'" in cond and "'pending'" in cond
    assert "stale" not in cond


def test_issue_and_archive_steps_stay_gated_on_changed_only() -> None:
    for name in ("Open tranche-detected issue", "Install asset-archive deps", "Run R2 asset archive"):
        cond = str(_step(name)["if"])
        assert "'changed'" in cond
        for other in ("benign", "pending", "stale"):
            assert other not in cond, (name, other)


def test_committed_guard_state_file_exists_and_matches_last_known() -> None:
    import json

    guard = json.loads((REPO_ROOT / "data" / "poll-state.json").read_text())
    last_known = (REPO_ROOT / "data" / "last-known-csv-sha.txt").read_text().split()[0]
    assert guard["current_sha"] == last_known
    assert guard["seen"][-1] == last_known
    assert guard["current_last_modified"]
    assert guard["pending"] is None
