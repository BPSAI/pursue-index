"""Tests for the Sprint 4e Phase 4 additions to
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
re-pinned here; this file is scoped to the Sprint 4e additions only.
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


def test_signing_verify_step_configures_ssh_signing_format() -> None:
    """The verify needs to use SSH-format signatures with the
    repo-tracked allowed_signers file. Without this config, ``git tag
    -v`` would fall back to GPG and fail.
    """
    step = _step("Verify latest signed registry-root tag")
    env = step["env"]
    git_config = env["GIT_CONFIG_PARAMETERS"]
    assert "gpg.format=ssh" in git_config
    assert "gpg.ssh.allowedSignersFile=docs/allowed-signers.txt" in git_config


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
