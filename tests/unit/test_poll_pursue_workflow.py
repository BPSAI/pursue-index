"""Tests for ``.github/workflows/poll-pursue.yml``.

The workflow is the wiring between the CSV poll, the new PDF-fetch
health check, and the GH-issue alert pipeline. We can't run the cron
in unit tests, but we *can* pin the file's structure so a careless
edit can't silently disable an alert path.

Constraints:

- The workflow must be valid YAML (typo / indent guard).
- The PDF-fetch health check step must exist and run AFTER the CSV
  poll step (so a hard failure in the CSV step doesn't suppress the
  PDF surveillance lane via early-step ordering).
- The PDF-failure issue step must be gated on the health step's
  `outcome == 'failure'`, NOT on the CSV poll's outputs (the two
  alert paths must not bleed into each other — a CSV-changed event
  should not also open a PDF-health issue).
- The propagate-failure step must include the PDF outcome so a
  PDF-only failure still goes red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "poll-pursue.yml"


def _load_steps() -> list[dict]:
    """Return the poll job's step list for ordered assertions."""
    data = yaml.safe_load(WORKFLOW.read_text())
    return data["jobs"]["poll"]["steps"]


def _step_index(steps: list[dict], needle: str) -> int:
    """First step where `needle` appears in `name`, `id`, or `run`."""
    for i, s in enumerate(steps):
        haystack = " ".join(
            str(s.get(k, "")) for k in ("name", "id", "uses", "run")
        )
        if needle in haystack:
            return i
    return -1


def test_poll_pursue_yaml_parses() -> None:
    """yaml.safe_load must succeed — guards typos, indent drift, etc."""
    yaml.safe_load(WORKFLOW.read_text())


def test_pdf_health_step_runs_after_csv_poll() -> None:
    """PDF check runs after the CSV poll. If we ever flip the order,
    a hard CSV-step crash could prevent PDF surveillance from running
    at all (continue-on-error doesn't help if the *workflow* exits)."""
    steps = _load_steps()
    poll_idx = _step_index(steps, "Run poll")
    pdf_idx = _step_index(steps, "Run PDF-fetch health check")
    assert poll_idx >= 0, "CSV poll step missing"
    assert pdf_idx >= 0, "PDF health step missing"
    assert pdf_idx > poll_idx, "PDF check must run after CSV poll"


def test_pdf_health_step_is_continue_on_error() -> None:
    """Without continue-on-error, a non-zero exit short-circuits the
    issue-opening step and the operator never gets paged."""
    steps = _load_steps()
    pdf_idx = _step_index(steps, "Run PDF-fetch health check")
    assert pdf_idx >= 0
    assert steps[pdf_idx].get("continue-on-error") is True


def test_pdf_failure_issue_is_gated_on_pdf_outcome_only() -> None:
    """The PDF-health issue must NOT fire on CSV outputs and the
    CSV-tranche issue must NOT fire on PDF outputs. The two
    surveillance lanes share the alert pipeline but stay independent."""
    steps = _load_steps()
    pdf_issue_idx = _step_index(steps, "Open pdf-health-failure issue")
    assert pdf_issue_idx >= 0, "PDF-failure issue step missing"

    condition = steps[pdf_issue_idx].get("if", "")
    assert "pdf_health" in condition, "PDF issue must reference pdf_health step"
    assert "steps.poll.outputs" not in condition, (
        "PDF issue must not be gated on CSV poll outputs (would conflate alert lanes)"
    )

    # And the inverse: the CSV-failure issue must NOT mention the PDF step.
    csv_fail_idx = _step_index(steps, "Open tranche-poll-failure issue")
    csv_condition = steps[csv_fail_idx].get("if", "")
    assert "pdf_health" not in csv_condition, (
        "CSV-failure issue must not be gated on PDF health (would bleed lanes)"
    )


def test_propagate_failure_covers_pdf_outcome() -> None:
    """If we don't propagate the PDF outcome to the workflow exit code,
    a green checkmark could ship while PDF surveillance was broken."""
    steps = _load_steps()
    propagate_idx = _step_index(steps, "Propagate failure exit code")
    assert propagate_idx >= 0
    condition = steps[propagate_idx].get("if", "")
    assert "pdf_health" in condition
    # CSV failure must still propagate too — don't accidentally drop it.
    assert "steps.poll" in condition


def test_pdf_health_label_created_in_label_seed_step() -> None:
    """`gh issue create --label foo` errors if the label doesn't exist;
    the label-seed step must include the new label name and apply
    --force so it's idempotent across cron re-runs."""
    steps = _load_steps()
    label_idx = _step_index(steps, "Ensure issue labels exist")
    assert label_idx >= 0
    run_block = steps[label_idx].get("run", "")
    # The new label must be created…
    assert "pdf-health-failure" in run_block
    # …and the gh-label-create call for it must use --force (idempotent).
    # Find the snippet of the run block that creates this specific label.
    after = run_block.split("pdf-health-failure", 1)[1]
    # `gh label create` blocks are short; the --force flag should appear
    # within ~10 lines of the label name.
    snippet = "\n".join(after.split("\n")[:10])
    assert "--force" in snippet


def test_pdf_health_step_invokes_dedicated_script() -> None:
    """The workflow runs the bare script (not the typer CLI) because
    the lean `requirements-poll.txt` install doesn't carry typer/rich.
    Pin that — flipping it back to `pursue ops pdf-health` would crash
    on a missing dep at the first cron tick."""
    steps = _load_steps()
    pdf_idx = _step_index(steps, "Run PDF-fetch health check")
    run_block = steps[pdf_idx].get("run", "")
    assert "scripts/pdf_health_check.py" in run_block
