"""Release-gate AC: deploy-side snapshot mirrors match pipeline-side.

Three invariants checked here, all cheap and CI-runnable without a
build step:

1. **Manifest coherence** — `web/src/data/manifest.json` (Astro build
   input) must byte-equal `data/manifests/latest.json` (pipeline
   source-of-truth). A drift means the build would ship the wrong
   manifest. This is the exact bug class fixed in commits 9b9b40d /
   ffeeddd on 2026-05-12.

2. **Snapshot file coverage** — `web/public/data/snapshots/` must
   contain a `.json` for every snapshot in `data/manifests/snapshots/`,
   and vice versa (no orphans). The DiffIsland UI reads from the
   web side; if pipeline writes a new snapshot but the mirror lags,
   the diff page goes stale (operator caught this with c9cc83fcaf43
   the day before this test landed).

3. **Snapshot index coverage** — `web/public/data/snapshots/index.json`
   must list exactly the snapshot files present on the web side. A
   missing entry hides a snapshot from the UI; an extra entry points
   at nothing.

Bonus: pairwise byte equality is checked when a snapshot exists on
both sides — if a file got desynced (corrupt copy, partial write),
this catches it without requiring a hash recomputation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PIPE_LATEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
_BUILD_MANIFEST = _REPO_ROOT / "web" / "src" / "data" / "manifest.json"
_PIPE_SNAPSHOTS = _REPO_ROOT / "data" / "manifests" / "snapshots"
_WEB_SNAPSHOTS = _REPO_ROOT / "web" / "public" / "data" / "snapshots"
_WEB_SNAPSHOTS_INDEX = _WEB_SNAPSHOTS / "index.json"


def _snapshot_files(d: Path) -> set[str]:
    """Names of `<sha>.json` snapshots in a directory (excludes index)."""
    if not d.is_dir():
        return set()
    return {p.name for p in d.glob("*.json") if p.name != "index.json"}


def test_pipeline_and_build_manifest_byte_equal() -> None:
    """`pursue ingest run` must mirror latest.json into both
    pipeline path AND web/src build path. Diff = stale Astro build."""
    pipe = _PIPE_LATEST.read_bytes()
    build = _BUILD_MANIFEST.read_bytes()
    if pipe != build:
        # Surface a useful diff hint
        pytest.fail(
            f"data/manifests/latest.json ({len(pipe)} bytes) != "
            f"web/src/data/manifest.json ({len(build)} bytes). "
            f"Run `pursue ingest run --tranche <sha>` to sync, then commit."
        )


def test_snapshot_files_mirror_both_directions() -> None:
    """Every pipeline snapshot is on the web side, and vice versa."""
    pipe = _snapshot_files(_PIPE_SNAPSHOTS)
    web = _snapshot_files(_WEB_SNAPSHOTS)
    only_pipe = pipe - web
    only_web = web - pipe
    if only_pipe or only_web:
        msg = []
        if only_pipe:
            msg.append(f"on pipeline but missing from web: {sorted(only_pipe)}")
        if only_web:
            msg.append(f"on web but missing from pipeline: {sorted(only_web)}")
        pytest.fail(
            "snapshot mirror is out of sync — "
            + "; ".join(msg)
            + ". Run `pursue ingest run --tranche <sha>` to re-mirror."
        )


def test_web_snapshot_index_covers_web_snapshot_files() -> None:
    """`web/public/data/snapshots/index.json` lists exactly the
    `<sha>.json` files actually present on the web side."""
    if not _WEB_SNAPSHOTS_INDEX.is_file():
        pytest.fail(f"missing {_WEB_SNAPSHOTS_INDEX}")
    # The index ships enriched {filename, fetched_at, card_count} objects
    # (so /diff selectors can label snapshots without fetching them), but
    # tolerate the legacy bare-string shape during any straddling deploy.
    raw = json.loads(_WEB_SNAPSHOTS_INDEX.read_text())
    listed = {e if isinstance(e, str) else e["filename"] for e in raw}
    present = _snapshot_files(_WEB_SNAPSHOTS)
    only_listed = listed - present
    only_present = present - listed
    if only_listed or only_present:
        msg = []
        if only_listed:
            msg.append(f"listed in index.json but file missing: {sorted(only_listed)}")
        if only_present:
            msg.append(f"file present but missing from index.json: {sorted(only_present)}")
        pytest.fail(
            "web/public/data/snapshots/index.json drifted from filesystem — "
            + "; ".join(msg)
        )


def test_snapshot_pairs_byte_equal_where_both_exist() -> None:
    """For every snapshot present on both sides, bytes must match.

    Catches the partial-write / corrupt-copy class. Rare but possible
    when `promote_snapshot` is interrupted mid-mirror.
    """
    pipe = _snapshot_files(_PIPE_SNAPSHOTS)
    web = _snapshot_files(_WEB_SNAPSHOTS)
    pairs = pipe & web

    drift: list[tuple[str, int, int]] = []
    for name in pairs:
        p_bytes = (_PIPE_SNAPSHOTS / name).read_bytes()
        w_bytes = (_WEB_SNAPSHOTS / name).read_bytes()
        if p_bytes != w_bytes:
            drift.append((name, len(p_bytes), len(w_bytes)))

    if drift:
        sample = "; ".join(f"{n} (pipe={p}b, web={w}b)" for n, p, w in drift[:5])
        pytest.fail(f"{len(drift)} snapshot(s) differ between pipeline + web mirror: {sample}")
