"""Structural guard for the silent-overlay step in verify-assets-daily.yml.

There's no YAML linter in CI (confirmed in the Sprint-6 poll work), so the
testable contract is: the workflow parses, and the silent-overlay step is wired
to the classify_overlay gate rather than firing on any appended registry row.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/verify-assets-daily.yml"
)


def _silent_overlay_step() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text())
    # `on:` parses to the python bool True as a key — irrelevant here.
    jobs = data["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if "silent overlay" in (step.get("name") or "").lower():
                return step
    raise AssertionError("silent-overlay step not found in workflow")


def test_workflow_yaml_parses() -> None:
    assert yaml.safe_load(WORKFLOW.read_text()) is not None


def test_overlay_step_gates_on_classifier_not_raw_append() -> None:
    """The step must classify appended rows and only alarm on a true overlay —
    not fire on every appended row (the net-new false-fire we're fixing)."""
    run = _silent_overlay_step()["run"]
    # Wired to the classifier + gated on the overlay count.
    assert "scripts/classify_overlay.py" in run
    assert "overlays" in run
    assert 'if [ "${overlays:-0}" -eq 0 ]' in run
    # The old behavior (open an issue keyed only on appended-row count) is gone.
    assert "added=$(git diff HEAD^ HEAD" not in run


def test_overlay_step_still_dedupes_and_creates_issue_on_real_overlay() -> None:
    run = _silent_overlay_step()["run"]
    assert "gh issue create" in run
    assert "silent-overlay-detected" in run
    assert "--label silent-overlay-detected --state open" in run  # dedup guard


def test_overlay_step_fails_loud_not_open_on_classifier_error() -> None:
    """A classifier crash / missing summary must fail the step, not silently
    default overlays to 0 and swallow a possible overlay (tamper-detection)."""
    run = _silent_overlay_step()["run"]
    assert "if ! classify=$(python scripts/classify_overlay.py" in run
    assert "grep -q '^overlay-classify '" in run
    assert run.count("exit 1") >= 2  # crash guard + missing-summary guard
