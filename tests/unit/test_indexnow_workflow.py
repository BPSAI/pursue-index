"""Tests for ``.github/workflows/indexnow-after-deploy.yml``.

Sprint 4b Theme B companion to the wayback-after-deploy workflow test.
Locks in the structural invariants:

* Path filter is narrowed from ``web/**`` to only paths that affect the
  rendered public site (same as wayback-after-deploy L3).
* The IndexNow step receives the ``INDEXNOW_KEY`` env var from the
  GitHub Actions secret of the same name (so the script can read it).
* The 5-min CFWB-wait runs only on ``push`` events, not workflow_dispatch.
* SHA-pinned action versions per SEC-001.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "indexnow-after-deploy.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job() -> dict:
    return _load()["jobs"]["indexnow-ping"]


def test_workflow_yaml_parses() -> None:
    """Guards against indent drift / typos."""
    _load()


def test_path_filter_is_narrowed_to_render_affecting_paths() -> None:
    """L3 (mirrors wayback): no triggers on state.md sweeps, docs/, OG re-render."""
    # YAML parses ``on:`` as the boolean True (PyYAML quirk pre-2.0).
    workflow = _load()
    on_block = workflow.get(True) or workflow.get("on")
    assert on_block is not None, "could not locate the `on:` block"
    push = on_block["push"]
    paths = push["paths"]
    # Allowed (render-affecting).
    for required in [
        "data/manifests/latest.json",
        "web/src/pages/**",
        "web/src/content/**",
        "web/src/components/**",
        "web/src/layouts/**",
    ]:
        assert required in paths, f"expected `{required}` in paths"
    # Forbidden (would trigger on state.md sweeps).
    assert "web/**" not in paths, (
        "broad `web/**` filter must be replaced by the narrowed render-"
        "affecting subset"
    )


def test_indexnow_step_receives_secret_via_env() -> None:
    """``INDEXNOW_KEY`` env must come from ``secrets.INDEXNOW_KEY``."""
    steps = _job()["steps"]
    submit_step = None
    for step in steps:
        if "Submit live sitemap URLs to IndexNow" in (step.get("name") or ""):
            submit_step = step
            break
    assert submit_step is not None, "submit step not found"
    env = submit_step.get("env") or {}
    assert env.get("INDEXNOW_KEY") == "${{ secrets.INDEXNOW_KEY }}", (
        "submit step must read INDEXNOW_KEY from the GitHub Actions secret "
        "of the same name; the script uses it as the env-var lookup key"
    )


def test_cfwb_wait_only_runs_on_push() -> None:
    """Workflow_dispatch is exempt from the 5-min sleep (operator ran it manually)."""
    steps = _job()["steps"]
    sleep_step = None
    for step in steps:
        if "Wait for CF Workers Builds" in (step.get("name") or ""):
            sleep_step = step
            break
    assert sleep_step is not None, "CFWB-wait step not found"
    assert sleep_step.get("if") == "github.event_name == 'push'", (
        "CFWB-wait step should be gated to push events so an operator-"
        "triggered re-ping isn't forced to wait 5 minutes"
    )


def test_actions_pinned_by_sha() -> None:
    """SEC-001: all third-party actions must be pinned by full SHA, not by tag."""
    steps = _job()["steps"]
    third_party = [s for s in steps if "uses" in s]
    assert len(third_party) >= 2, "expected actions/checkout + setup-python steps"
    for step in third_party:
        uses = step["uses"]
        # Full SHA looks like `name@<40-hex>`. Tag-pinned looks like `name@v6`.
        owner_repo, ref = uses.rsplit("@", 1)
        assert len(ref) == 40, (
            f"{owner_repo} is pinned to `{ref}` — must use a 40-char SHA, "
            "not a tag (per SEC-001)"
        )


def test_concurrency_group_named_to_serialize_self() -> None:
    """Concurrent dispatches of this workflow must serialize."""
    workflow = _load()
    conc = workflow["concurrency"]
    assert conc["group"] == "indexnow-after-deploy"
    assert conc["cancel-in-progress"] is False, (
        "Do not cancel a running ping; a partial submission may have left "
        "state in IndexNow's queue. Let the prior run finish."
    )
