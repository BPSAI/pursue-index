"""Tests for ``.github/workflows/close-tranche-on-promote.yml``.

Sprint 4d. Locks in the structural invariants:

* Trigger is narrowed to ``data/manifests/latest.json`` (so unrelated
  main pushes don't fire) plus ``workflow_dispatch`` for manual re-runs.
* Permissions block grants ``issues: write`` (required) and ``contents:
  read`` (default-safe).
* The closer step exports ``GH_TOKEN`` / ``GITHUB_SHA`` /
  ``GITHUB_REPOSITORY`` for the script.
* SHA-pinned action versions per SEC-001 (matching the pins used by
  the sibling post-deploy workflows).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "close-tranche-on-promote.yml"


def _load() -> dict:
    # See test_indexnow_workflow._load for the ``on:`` -> True quirk.
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict:
    return _load()["jobs"]["close-matching-tranche-issue"]


def test_workflow_yaml_parses() -> None:
    _load()


def test_trigger_narrowed_to_manifest_changes() -> None:
    workflow = _load()
    on_block = workflow.get(True) or workflow.get("on")
    assert on_block is not None
    push = on_block["push"]
    assert push["branches"] == ["main"]
    assert push["paths"] == ["data/manifests/latest.json"]
    # workflow_dispatch present so the operator can re-run manually.
    assert "workflow_dispatch" in on_block


def test_permissions_grant_issue_write_and_read_contents() -> None:
    perms = _load()["permissions"]
    assert perms["issues"] == "write"
    assert perms["contents"] == "read"


def test_closer_step_exports_gh_token_and_repo_context() -> None:
    steps = _job()["steps"]
    closer = next(s for s in steps if s.get("name", "").startswith("Close matching"))
    env = closer["env"]
    assert env["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert env["GITHUB_SHA"] == "${{ github.sha }}"
    assert env["GITHUB_REPOSITORY"] == "${{ github.repository }}"


def test_action_versions_are_sha_pinned() -> None:
    """SEC-001: actions referenced by SHA, not floating tag."""
    steps = _job()["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    for ref in uses:
        # SHA-pinned references have @<40-hex>; tag-pinned have @vN.
        sha = ref.split("@", 1)[1]
        assert len(sha) == 40 and all(
            c in "0123456789abcdef" for c in sha.lower()
        ), f"{ref} is not SHA-pinned"


def test_concurrency_group_prevents_overlap() -> None:
    """A second promote landing within seconds of the first should
    queue (or skip), not race the first's close.

    nayru M1: ``cancel-in-progress: false`` is load-bearing here — a
    flip to True would let a fast second push cancel the first run
    mid-close, leaving an issue partially-commented or
    not-closed-but-commented. Pin it explicitly so a future
    "make-it-snappy" refactor surfaces as a test failure.
    """
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "close-tranche-on-promote"
    assert concurrency["cancel-in-progress"] is False


def test_invokes_close_script_with_default_manifest() -> None:
    steps = _job()["steps"]
    closer = next(s for s in steps if s.get("name", "").startswith("Close matching"))
    cmd = closer["run"]
    assert "scripts/close_tranche_issues_on_promote.py" in cmd
    assert "--manifest data/manifests/latest.json" in cmd
