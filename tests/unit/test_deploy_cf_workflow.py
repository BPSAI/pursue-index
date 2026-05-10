"""Tests for ``.github/workflows/deploy-cf.yml``.

Constraints:

- The workflow must be valid YAML.
- The OG-image build steps must run BEFORE ``npm run build`` so the
  Astro build sees freshly-rendered ``web/public/og.png`` and
  ``web/public/og/finds/*.png`` (the build copies ``web/public`` into
  ``web/dist`` — stale OG images would otherwise ship to production
  whenever the manifest sha changes or a new finds entry lands).
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-cf.yml"


def _load_steps() -> list[dict]:
    """Return the deploy job's step list for ordered assertions."""
    data = yaml.safe_load(WORKFLOW.read_text())
    return data["jobs"]["deploy"]["steps"]


def test_deploy_cf_yaml_parses() -> None:
    """yaml.safe_load must succeed — guards typos, indent drift, etc."""
    yaml.safe_load(WORKFLOW.read_text())


def test_deploy_cf_includes_og_build_steps() -> None:
    """Both OG build scripts must be invoked in the deploy job."""
    steps_text = WORKFLOW.read_text()
    assert "build_og_image.py" in steps_text, (
        "default OG image build script not wired into deploy-cf.yml"
    )
    assert "build_finds_og_images.py" in steps_text, (
        "per-entry finds OG build script not wired into deploy-cf.yml"
    )


def test_og_build_runs_before_npm_build() -> None:
    """``npm run build`` reads ``web/public/`` — OG images must be
    rendered before the Astro build copies the public dir into dist."""
    steps = _load_steps()
    names = [s.get("name") or s.get("uses") or "" for s in steps]
    runs = [s.get("run", "") for s in steps]

    def _index_of(needle: str) -> int:
        for i, (n, r) in enumerate(zip(names, runs, strict=False)):
            if needle in n or needle in r:
                return i
        return -1

    npm_build_idx = _index_of("npm run build")
    og_idx = _index_of("build_og_image.py")
    finds_og_idx = _index_of("build_finds_og_images.py")
    assert og_idx >= 0
    assert finds_og_idx >= 0
    assert npm_build_idx >= 0
    assert og_idx < npm_build_idx, "build_og_image.py must run before npm run build"
    assert finds_og_idx < npm_build_idx, (
        "build_finds_og_images.py must run before npm run build"
    )


def test_setup_python_uses_pinned_sha() -> None:
    """SEC-001 (poll-pursue.yml audit): GitHub Actions must be pinned
    to commit SHAs, not tag refs. The setup-python entry must use a
    40-char hex sha matching the pattern used elsewhere in the repo."""
    text = WORKFLOW.read_text()
    assert "actions/setup-python@" in text, "setup-python step missing"
    # Match the same SHA used in poll-pursue.yml for consistency.
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in text
