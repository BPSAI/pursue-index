"""Tests for ``.github/workflows/registry-root-on-promote.yml``.

Sprint 4e Phase 3. Locks the structural invariants:

* Trigger covers BOTH the registry and the root file (a direct edit
  to either should surface drift on the next push).
* Permissions are minimum: ``contents: read``. No commits, no issue
  writes — this workflow is supposed to fail loudly, not auto-heal.
* SHA-pinned actions per SEC-001 (matches sibling workflows).
* The verify step is the right script + the right args (especially
  the empty ``--signed-source`` — the daily verify covers the
  divergence-locator side).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "registry-root-on-promote.yml"


def _load() -> dict:
    # See test_indexnow_workflow._load for the ``on:`` -> True quirk.
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict:
    return _load()["jobs"]["verify-registry-root"]


def test_workflow_yaml_parses() -> None:
    _load()


def test_trigger_covers_registry_and_root_file_paths() -> None:
    """Both the registry and the recorded root file are triggers —
    a tamper attack might touch either side."""
    workflow = _load()
    on_block = workflow.get(True) or workflow.get("on")
    push = on_block["push"]
    assert push["branches"] == ["main"]
    paths = push["paths"]
    assert "data/asset-bytes-registry.jsonl" in paths
    assert "data/registry-root.txt" in paths
    assert "workflow_dispatch" in on_block


def test_permissions_are_minimal_contents_read_only() -> None:
    """This workflow doesn't commit, doesn't comment, doesn't write
    issues — it's allowed to fail loudly. Minimum-viable permission
    is contents:read for the checkout step."""
    perms = _load()["permissions"]
    assert perms["contents"] == "read"
    # Explicitly no other writes.
    assert "issues" not in perms or perms.get("issues") != "write"
    assert "pull-requests" not in perms


def test_concurrency_group_prevents_overlap() -> None:
    """Same posture as the close-tranche workflow — queue, not
    cancel-in-progress (a flapping registry shouldn't mask earlier
    failures by cancelling them)."""
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "registry-root-on-promote"
    assert concurrency["cancel-in-progress"] is False


def test_action_versions_are_sha_pinned() -> None:
    steps = _job()["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    for ref in uses:
        sha = ref.split("@", 1)[1]
        assert len(sha) == 40 and all(
            c in "0123456789abcdef" for c in sha.lower()
        ), f"{ref} is not SHA-pinned"


def test_verify_step_invokes_verify_script_with_empty_signed_source() -> None:
    """Per-push verify is root-freshness only; divergence localization
    lives in the daily lane where the signed tag's contents are
    accessible. Empty ``--signed-source`` here is intentional."""
    steps = _job()["steps"]
    verify_step = next(
        s for s in steps if s.get("name", "").startswith("Verify registry-root")
    )
    cmd = verify_step["run"]
    assert "scripts/verify_registry_root.py" in cmd
    assert "--registry data/asset-bytes-registry.jsonl" in cmd
    assert "--root data/registry-root.txt" in cmd
    assert '--signed-source ""' in cmd
