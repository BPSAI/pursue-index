"""Tests for the tag-verify additions to
``.github/workflows/verify-assets-daily.yml``.

Locks the structural invariants of the new tag-verify lane:

* The checkout step now fetches tags (default fetch-depth: 1 doesn't
  pull tags, and ``git tag -v`` needs the signed tag locally).
* A ``Verify latest signed registry-root tag`` step exists, exports
  ``signing_state`` via ``$GITHUB_OUTPUT``, and is gated to never
  fail-the-workflow so a key-rotation hiccup doesn't suppress the
  silent-overlay detection lane above.
* A separate issue-filing step files ``signing-failure`` only when
  the previous step's ``signing_state == 'failed'``.
* ``gpg.format=ssh`` + ``gpg.ssh.allowedSignersFile=docs/allowed-signers.txt``
  are configured for the verify step.

The existing lanes (silent-overlay + preserved-tampered) are not
re-pinned here; this file is scoped to the tag-verify additions only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-assets-daily.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict:
    return _load()["jobs"]["verify"]


def _step(prefix: str) -> dict:
    for step in _job()["steps"]:
        name = step.get("name", "")
        if name.startswith(prefix):
            return step
    raise AssertionError(f"step starting with {prefix!r} not found in workflow")


def test_workflow_yaml_parses() -> None:
    _load()


def test_checkout_fetches_tags() -> None:
    """Default fetch-depth: 1 doesn't include tags. The new tag-verify
    step needs ``git tag -v`` to find the signed registry-root tags
    locally."""
    steps = _job()["steps"]
    checkout = next(s for s in steps if "uses" in s and s["uses"].startswith("actions/checkout@"))
    assert checkout["with"].get("fetch-tags") is True


def test_signing_verify_step_exists_with_id_signing() -> None:
    step = _step("Verify latest signed registry-root tag")
    assert step["id"] == "signing"
    # continue-on-error so a key-rotation hiccup doesn't suppress the
    # silent-overlay detection lane above this one.
    assert step["continue-on-error"] is True


def test_signing_verify_step_pins_to_operator_secret() -> None:
    """``.verification.verified == true`` only confirms
    "valid against ANY GitHub-registered signing key" — a repo:write
    attacker with their own registered Signing key can satisfy that.
    Pin verification to exactly the operator key via the
    ``OPERATOR_ALLOWED_SIGNERS`` GitHub Actions secret (modifiable
    only by repo admin/maintain, not by repo:write contributors).
    """
    step = _step("Verify latest signed registry-root tag")
    cmd = step["run"]
    env = step.get("env") or {}
    # Trust anchor is the secret, materialized to a runner-local file.
    assert env.get("OPERATOR_ALLOWED_SIGNERS") == "${{ secrets.OPERATOR_ALLOWED_SIGNERS }}"
    assert "$OPERATOR_ALLOWED_SIGNERS" in cmd
    assert "trusted-signers.txt" in cmd
    # Verification is git tag -v against the SECRET's allowed-signers,
    # NOT gh api .verification.verified (the previous design was
    # flagged as too permissive).
    assert "git -c gpg.format=ssh" in cmd
    assert "gpg.ssh.allowedSignersFile=" in cmd
    assert "tag -v" in cmd
    assert "gh api" not in cmd or ".verification.verified" not in cmd
    # Repo-tracked allowed-signers file MUST NOT be the trust anchor.
    assert "docs/allowed-signers.txt" not in cmd


def test_signing_verify_step_emits_unconfigured_state_when_secret_unset() -> None:
    """Before the operator sets ``OPERATOR_ALLOWED_SIGNERS``, the
    verify step exits 0 with ``signing_state=unconfigured`` and a
    ``::warning::`` — the workflow shouldn't paint red just because
    the operator hasn't completed setup.
    """
    step = _step("Verify latest signed registry-root tag")
    cmd = step["run"]
    assert "signing_state=unconfigured" in cmd
    assert "OPERATOR_ALLOWED_SIGNERS" in cmd


def test_signing_verify_step_binds_to_current_registry_root() -> None:
    """A valid signed tag pointing at an older
    registry-root.txt MUST NOT pass verification — that would leave
    current state unsigned. The step compares the signed tag's
    registry-root.txt against the current HEAD's file.
    """
    step = _step("Verify latest signed registry-root tag")
    cmd = step["run"]
    assert "git show" in cmd
    assert ":data/registry-root.txt" in cmd
    assert "signing_state=stale" in cmd


def test_signing_verify_step_handles_bootstrap_window() -> None:
    """When no ``registry-root-*`` tag exists yet (before the
    operator signs the baseline), the step exits 0 with a notice
    and reports ``signing_state=bootstrap`` via $GITHUB_OUTPUT."""
    step = _step("Verify latest signed registry-root tag")
    cmd = step["run"]
    assert "registry-root-*" in cmd
    assert "signing_state=bootstrap" in cmd
    assert "signing_state=verified" in cmd
    assert "signing_state=failed" in cmd


def test_signing_failure_issue_step_is_gated_on_signing_state() -> None:
    """Issue creation must fire only when the verify step reports a
    real failure — bootstrap state must NOT spam issues."""
    step = _step("Open issue when signing verification fails")
    assert "steps.signing.outputs.signing_state == 'failed'" in step["if"]


def test_signing_failure_issue_uses_signing_failure_label() -> None:
    step = _step("Open issue when signing verification fails")
    cmd = step["run"]
    assert "signing-failure" in cmd
    # Dedup so a daily-cron re-fire doesn't open duplicate issues.
    assert "--label signing-failure" in cmd
    assert "exit 0" in cmd  # dedup-already-open path


def test_signing_stale_issue_step_exists_with_distinct_label() -> None:
    """A valid-but-stale tag
    (HEAD root differs from signed root) gets its own
    ``signing-stale`` label, distinct from ``signing-failure``.
    Operator response is different — sign a fresh tag, not roll
    back. The two labels keep the operator queue legible.
    """
    step = _step("Open issue when latest signed tag is stale")
    assert "steps.signing.outputs.signing_state == 'stale'" in step["if"]
    cmd = step["run"]
    assert "signing-stale" in cmd
    assert "--label signing-stale" in cmd
    # Issue body must direct operator to the runbook so they know to
    # sign a fresh tag (not roll back).
    assert "registry-root-signing.md" in cmd
