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


def _load_jobs() -> dict:
    """Return the workflow's full ``jobs`` map."""
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _load_steps() -> list[dict]:
    """Return the poll job's step list for ordered assertions."""
    return _load_jobs()["poll"]["steps"]


def _contains_token(node: object, token: str) -> bool:
    """True if ``token`` appears anywhere in the parsed (comment-free)
    structure ``node`` — keys, scalar values, nested lists/dicts. Used to
    prove a secret name is *absent* from a job's parsed body (comments are
    stripped by ``safe_load``, so a documenting ``# ... R2_ACCESS_KEY_ID``
    header can't produce a false positive)."""
    if isinstance(node, dict):
        return any(
            token in str(k) or _contains_token(v, token) for k, v in node.items()
        )
    if isinstance(node, list):
        return any(_contains_token(v, token) for v in node)
    return token in str(node)


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
    """yaml.safe_load must succeed AND the trigger block must be wired.

    PyYAML 1.1 silently casts unquoted ``on:`` to Python ``True``, so a
    plain ``safe_load`` succeeds even when the trigger block is empty
    or malformed. Drill into the trigger map to confirm both
    ``schedule`` and ``workflow_dispatch`` are present and the cron
    expression is non-empty. (nayru P1#2)
    """
    data = yaml.safe_load(WORKFLOW.read_text())

    # PyYAML 1.1 may key the unquoted ``on:`` block under True (bool) or "on" (str).
    triggers = data.get("on") if "on" in data else data.get(True)
    assert triggers is not None, "workflow has no trigger block"
    assert "schedule" in triggers, "workflow missing 'schedule' trigger"
    assert "workflow_dispatch" in triggers, "workflow missing 'workflow_dispatch' trigger"

    schedule = triggers["schedule"]
    # ``schedule`` is a list of dicts each with a ``cron`` key.
    assert isinstance(schedule, list) and schedule, "schedule must be a non-empty list"
    cron_expr = schedule[0].get("cron", "")
    assert cron_expr, "cron expression must be non-empty"


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


def test_pdf_health_runs_regardless_of_earlier_failures() -> None:
    """Codex P2 review (2026-05-10): without an explicit `if`, GitHub's
    default `success()` gate skips this step if any earlier non-
    continue-on-error step (like `gh issue create` for CSV) failed.
    That defeats the entire independent-PDF-surveillance design.
    `if: always()` keeps the lane truly independent."""
    steps = _load_steps()
    pdf_idx = _step_index(steps, "Run PDF-fetch health check")
    assert pdf_idx >= 0
    if_clause = steps[pdf_idx].get("if", "")
    # Accept either form GitHub recognizes as "always run".
    assert "always" in if_clause or "!cancelled" in if_clause, (
        f"PDF health step must run unconditionally (always() / !cancelled()), "
        f"got if={if_clause!r}"
    )


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


def test_pdf_health_issue_step_has_dedup_guard() -> None:
    """Without a search-before-create guard, every failing 6h cron tick
    opens a *new* pdf-health-failure issue. After 24 hours of an outage
    the operator has 4 duplicate issues and the alert lane is noisy
    enough to be ignored. (laverna SEC-001)

    The guard pattern: ``gh issue list --label pdf-health-failure
    --state open ...`` must appear before ``gh issue create`` within
    the same step's run block.
    """
    steps = _load_steps()
    pdf_issue_idx = _step_index(steps, "Open pdf-health-failure issue")
    assert pdf_issue_idx >= 0, "PDF-failure issue step missing"
    run_block = steps[pdf_issue_idx].get("run", "")

    list_pos = run_block.find("gh issue list")
    create_pos = run_block.find("gh issue create")
    assert list_pos >= 0, "PDF issue step missing 'gh issue list' dedup probe"
    assert create_pos >= 0, "PDF issue step missing 'gh issue create'"
    assert list_pos < create_pos, (
        "dedup probe ('gh issue list') must run BEFORE 'gh issue create'"
    )
    assert "pdf-health-failure" in run_block[:list_pos + 200]


def test_pdf_health_step_invokes_dedicated_script() -> None:
    """The workflow runs the bare script (not the typer CLI) because
    the lean `requirements-poll.txt` install doesn't carry typer/rich.
    Pin that — flipping it back to `pursue ops pdf-health` would crash
    on a missing dep at the first cron tick."""
    steps = _load_steps()
    pdf_idx = _step_index(steps, "Run PDF-fetch health check")
    run_block = steps[pdf_idx].get("run", "")
    assert "scripts/pdf_health_check.py" in run_block


# ---------------------------------------------------------------------------
# Snapshot + diff lane (Sprint 6, T6.2). The credential-free generator job.
# ---------------------------------------------------------------------------


def test_snapshot_job_exists() -> None:
    """The offline snapshot+diff generator runs as its OWN job, not a
    step welded into the credentialed `poll` job — that separation is
    what keeps R2/CF secrets out of the generator's runner."""
    jobs = _load_jobs()
    assert "snapshot" in jobs, "snapshot job missing from workflow"


def test_snapshot_job_has_no_r2_cf_secrets() -> None:
    """AC1 — the snapshot job's body must contain NO R2/CF write
    credentials. Scans the whole parsed job (job + step env, run blocks),
    a superset of the `env:` block the AC names. Comments are stripped by
    safe_load, so the documenting header naming these secrets can't trip
    this."""
    snapshot = _load_jobs()["snapshot"]
    for secret in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "CF_ACCOUNT_ID"):
        assert not _contains_token(snapshot, secret), (
            f"snapshot job must not reference {secret} (credential isolation)"
        )


def test_snapshot_job_runs_only_on_detected_change() -> None:
    """AC2 — gated on the poll job's `status == 'changed'` output. On an
    unchanged/failed poll there is no new side to snapshot."""
    snapshot = _load_jobs()["snapshot"]
    if_clause = str(snapshot.get("if", ""))
    assert "needs.poll.outputs.status" in if_clause
    assert "changed" in if_clause


def test_snapshot_job_survives_unrelated_poll_failure() -> None:
    """The poll job deliberately ``exit 1``s on a PDF-health-sentinel failure
    (an independent surveillance lane). With a bare ``needs: poll`` gate,
    GitHub treats the job ``if`` as implicitly ``success() && …`` — so a
    CSV-changed run where only the PDF lane failed would SKIP the snapshot,
    losing the credential-free snapshot for exactly the detected change this
    job exists to preserve. The gate must use ``always()`` to decouple from
    the poll job's overall result while still gating on the detected change.
    (Codex PR #84 P2.)"""
    if_clause = str(_load_jobs()["snapshot"].get("if", ""))
    assert "always()" in if_clause, (
        "snapshot job `if` must use always() so an unrelated poll-step "
        "failure (e.g. PDF health) does not skip the snapshot"
    )
    # Still gated on the detected change — always() must not run it on no-change.
    assert "needs.poll.outputs.status" in if_clause and "changed" in if_clause


def test_snapshot_job_runs_generator_and_commits() -> None:
    """AC2 — a step invokes the T6.1 generator script and a step commits
    the snapshot + diff JSON. Like pdf_health, it runs the bare script
    (lean requirements-poll.txt has no typer/rich)."""
    steps = _load_jobs()["snapshot"]["steps"]
    blob = " ".join(str(s.get("run", "")) for s in steps)
    assert "scripts/poll_snapshot.py" in blob, "snapshot job must run the T6.1 generator"
    assert "git commit" in blob and "git push" in blob, "snapshot job must commit + push"
    # The committed artifacts are the canonical + public snapshot mirrors.
    assert "data/manifests/snapshots" in blob
    assert "web/public/data/snapshots" in blob


def test_snapshot_job_serializes_on_registry_writers_group() -> None:
    """Serialization: the snapshot job pushes to main, so it must not race
    the poll job's sha/bytes commit. Cross-run serialization comes from the
    workflow-level `pursue-registry-writers` concurrency group (the whole
    workflow is bound to it); intra-run ordering comes from `needs: poll`,
    which also makes the poll outputs available. A redundant job-level
    concurrency of the SAME group is deliberately omitted — it would
    deadlock against the workflow-level lock."""
    data = yaml.safe_load(WORKFLOW.read_text())
    assert data["concurrency"]["group"] == "pursue-registry-writers"
    snapshot = data["jobs"]["snapshot"]
    needs = snapshot.get("needs", [])
    needs = [needs] if isinstance(needs, str) else needs
    assert "poll" in needs, "snapshot job must `needs: poll` to serialize after it"


def test_poll_job_exposes_outputs_for_snapshot() -> None:
    """For `needs.poll.outputs.*` to resolve, the poll job must promote its
    step outputs to job-level outputs. Without this the snapshot gate is
    always empty and never fires."""
    poll = _load_jobs()["poll"]
    outputs = poll.get("outputs", {})
    assert "status" in outputs, "poll job must expose `status` output"
    assert "new_sha" in outputs, "poll job must expose `new_sha` output"


# ---------------------------------------------------------------------------
# Surface the classify_tranche verdict (Sprint 6, T6.4). The snapshot job
# computes the verdict, commits a diff+verdict JSON artifact, and appends the
# verdict to the existing tranche-detected issue located by new_sha.
# ---------------------------------------------------------------------------


def _snapshot_steps() -> list[dict]:
    return _load_jobs()["snapshot"]["steps"]


def test_snapshot_generate_step_writes_diff_artifact() -> None:
    """AC1 — the generate step must pass ``--diff-out`` so the T6.1 generator
    persists the diff+verdict JSON artifact (not just the kv log line)."""
    blob = " ".join(str(s.get("run", "")) for s in _snapshot_steps())
    assert "scripts/poll_snapshot.py" in blob
    assert "--diff-out" in blob, "generate step must write the verdict artifact"


def test_snapshot_commit_step_includes_diff_artifact() -> None:
    """AC1 — the diff+verdict JSON must be committed alongside the snapshot
    mirrors. The committed artifact path must be the same one written via
    --diff-out (a single source of truth, not two divergent paths)."""
    steps = _snapshot_steps()
    blob = " ".join(str(s.get("run", "")) for s in steps)
    # Pull the --diff-out path and assert it's both written and git-added.
    tokens = blob.split()
    diff_out = tokens[tokens.index("--diff-out") + 1].strip('"').strip("'")
    assert diff_out, "no --diff-out path found"
    # The committed mirror dir that holds the artifact must be git-added.
    assert "git add" in blob
    # The artifact path (or its parent dir) must appear in a git add.
    add_region = blob.split("git add", 1)[1]
    parent = diff_out.rsplit("/", 1)[0]
    assert diff_out in add_region or parent in add_region, (
        "diff+verdict artifact must be committed (git add of its path/dir)"
    )


def test_snapshot_job_comments_verdict_on_issue_by_new_sha() -> None:
    """AC2 — a step appends the verdict to the existing tranche-detected
    issue, located by new_sha (gh issue list + gh issue comment/edit).
    Tested structurally — no live GitHub call."""
    steps = _snapshot_steps()
    idx = _step_index(steps, "Append verdict")
    assert idx >= 0, "snapshot job missing a verdict-comment step"
    step = steps[idx]
    run_block = str(step.get("run", ""))
    # Locates the issue by new_sha, then comments/edits it.
    assert "new_sha" in str(step.get("env", "")) + run_block, (
        "verdict step must locate the issue by new_sha"
    )
    assert "gh issue list" in run_block, "must locate the existing issue"
    assert "gh issue comment" in run_block or "gh issue edit" in run_block, (
        "verdict step must append to the existing issue (comment/edit)"
    )
    # The comment must carry the verdict artifact / rendered summary.
    assert "diff" in run_block.lower() or "verdict" in run_block.lower()


def test_snapshot_verdict_step_keeps_early_alert_intact() -> None:
    """The verdict is ADDED to the existing issue, not a replacement for the
    early tranche-detected alert: the verdict step must NOT call
    ``gh issue create`` (that would open a duplicate / collapse the
    credential-isolation job split)."""
    steps = _snapshot_steps()
    idx = _step_index(steps, "Append verdict")
    assert idx >= 0
    run_block = str(steps[idx].get("run", ""))
    assert "gh issue create" not in run_block, (
        "verdict step must append to the existing issue, not create a new one"
    )


def test_snapshot_job_credential_isolation_documented() -> None:
    """AC4 — a header comment must document WHY the job is credential-
    isolated (comments are stripped by safe_load, so assert on raw text,
    in the region above the `snapshot:` job key)."""
    text = WORKFLOW.read_text()
    job_pos = text.find("\n  snapshot:")
    assert job_pos > 0, "snapshot job key not found"
    header = text[:job_pos]
    # The most recent comment block before the job must explain isolation.
    tail = header[-1600:]
    assert "credential" in tail.lower()
    assert "R2" in tail and "isolat" in tail.lower()
