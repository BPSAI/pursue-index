"""Tests for ``.github/workflows/wayback-after-deploy.yml``.

Locks in the fixes from PR #65 review (H2/H3/H4/L3/L4):

* H2: commit-back step must ``git add`` BEFORE diff-checking so newly
  created (untracked) history files trigger a commit.
* H3: commit-back step has ``if: always()`` so per-URL failures still
  persist freshness state.
* H4: commit-back step ``git pull --rebase`` before ``git push`` so a
  concurrent registry writer doesn't lose to a non-fast-forward.
* L3: path filter is narrowed from ``web/**`` to only paths that affect
  the rendered public site (no state.md/docs sweeps trigger Wayback).
* L4: CFWB dependency is documented in the file header.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "wayback-after-deploy.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _commit_back_step() -> dict:
    """Return the dict for the 'Commit updated wayback-history.json' step."""
    steps = _load()["jobs"]["wayback-save"]["steps"]
    for step in steps:
        if "Commit updated wayback-history.json" in (step.get("name") or ""):
            return step
    raise AssertionError("commit-back step not found")


def test_workflow_yaml_parses() -> None:
    """Guards against indent drift / typos."""
    _load()


def test_commit_step_has_if_always() -> None:
    """H3: commit-back must run even when the prior step emitted warnings."""
    step = _commit_back_step()
    assert step.get("if") == "always()", (
        "H3: commit-back step must use `if: always()` so per-URL warnings "
        "do not skip the freshness-state persistence"
    )


def test_commit_step_stages_before_diff_check() -> None:
    """H2: ``git add`` must precede the diff check.

    ``git diff --quiet <path>`` does NOT detect untracked (newly
    created) files. The first run of the script writes a new
    ``data/wayback-history.json`` from scratch — without the stage
    step the diff says "no change" and freshness state never gets
    committed back.
    """
    step = _commit_back_step()
    run = step["run"]
    add_idx = run.find("git add data/wayback-history.json")
    diff_idx = run.find("git diff --cached --quiet")
    assert add_idx >= 0, "expected `git add data/wayback-history.json` in commit step"
    assert diff_idx >= 0, (
        "expected `git diff --cached --quiet` in commit step (H2: --cached "
        "after staging, not plain `git diff` which misses untracked files)"
    )
    assert add_idx < diff_idx, (
        "H2: `git add` must precede the diff check so new files are not "
        "silently ignored"
    )


def test_commit_step_rebases_before_push() -> None:
    """H4: race-safety against concurrent writers to main."""
    step = _commit_back_step()
    run = step["run"]
    rebase_idx = run.find("git pull --rebase")
    push_idx = run.find("git push")
    assert rebase_idx >= 0, "H4: expected `git pull --rebase` before push"
    assert push_idx >= 0
    assert rebase_idx < push_idx, (
        "H4: rebase must precede push to avoid non-fast-forward failures "
        "when another workflow has written to main during this run"
    )


def test_commit_step_rebases_before_staging() -> None:
    """Codex re-review P1 (2026-05-17): rebase before stage.

    Git refuses to rebase with an uncommitted index — ``cannot pull
    with rebase: Your index contains uncommitted changes``. The
    fix-pass initially put ``git add`` before ``git pull --rebase``,
    which broke the workflow in the exact case it was supposed to
    handle (non-empty history changes). Order must be:
        1. ``git pull --rebase origin main``  (clean tree)
        2. ``git add data/wayback-history.json``
        3. diff check + commit + push
    """
    step = _commit_back_step()
    run = step["run"]
    rebase_idx = run.find("git pull --rebase")
    add_idx = run.find("git add data/wayback-history.json")
    assert rebase_idx >= 0, "expected `git pull --rebase` in commit step"
    assert add_idx >= 0, "expected `git add` in commit step"
    assert rebase_idx < add_idx, (
        "Codex P1: `git pull --rebase` must precede `git add` so the "
        "rebase runs on a clean index (git refuses rebase with staged "
        "changes)"
    )


def test_path_filter_is_narrowed_to_render_affecting_paths() -> None:
    """L3 (vaivora): trigger paths exclude state.md / docs / OG-only commits.

    The pre-fix filter was ``web/**``, which fired on every meaningful
    push touching the web tree — including state.md sweeps from the
    paircoder hooks (which never change rendered HTML) and docs
    subdirs. CI minute cost was non-trivial. Narrowed list contains
    only paths whose change actually affects the public site.
    """
    data = _load()
    # YAML quirk: `on:` parses as bool True under safe_load. Look up
    # either key form.
    on_block = data.get("on") or data.get(True)
    assert on_block, "workflow must define triggers"
    paths = on_block["push"]["paths"]
    # Manifest changes always warrant a fresh snapshot.
    assert "data/manifests/latest.json" in paths
    # Source code paths that affect rendered HTML — pages, content,
    # components, layouts. Public dir (OG bot output) is intentionally
    # absent because OG image changes don't change the public URL.
    assert any("web/src/pages" in p for p in paths)
    assert any("web/src/content" in p for p in paths)
    assert any("web/src/components" in p for p in paths)
    assert any("web/src/layouts" in p for p in paths)
    # The over-broad `web/**` must be gone.
    assert "web/**" not in paths, (
        "L3: `web/**` is too broad — narrow to render-affecting subdirs"
    )


def test_workflow_documents_cfwb_dependency() -> None:
    """L4: file header must explain the CF Workers Builds timing dep."""
    text = WORKFLOW.read_text()
    assert "CF Workers Builds" in text or "CFWB" in text, (
        "L4: the 5-min sleep is timed against the CF Workers Builds "
        "dashboard pipeline — this should be documented inline so a "
        "future operator doesn't assume it ties to deploy-cf.yml"
    )


def test_workflow_uses_pinned_action_shas() -> None:
    """SEC-001: pinned to commit SHAs, not tag refs."""
    text = WORKFLOW.read_text()
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in text
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in text
