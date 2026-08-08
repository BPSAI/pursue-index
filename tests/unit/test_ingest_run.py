"""Tests for the ingest-run orchestrator (plan step 7).

The orchestrator is a thin shell: gate-check, snapshot promotion to
latest.json, and a summary of what downstream stages need to run.
Heavy lifting (download/ocr/embed) stays under the existing pursue
download/ocr/embed CLI surfaces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.ingest_run import (  # noqa: E402
    locate_snapshot,
    promote_snapshot,
    render_next_steps,
    summarize_ingest_work,
)


def test_render_next_steps_ocr_uses_operated_engine() -> None:
    """The post-tranche runbook must instruct the operator to run the operated
    engine (llm-dots), never the retired 'auto' resolver."""
    summary = {
        "needs_download": ["card1"],
        "needs_ocr": ["card1"],
        "needs_embed": ["card1"],
        "needs_inspection": [],
        "metadata_only": False,
    }
    steps = render_next_steps(summary)
    assert "--engine llm-dots" in steps
    assert "--engine auto" not in steps


def test_locate_snapshot_finds_full_sha_match(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    full_sha = "abc123" + "0" * 58
    target = snapshots / f"{full_sha}.json"
    target.write_text("{}")
    assert locate_snapshot(full_sha, snapshots) == target


def test_locate_snapshot_finds_prefix_match(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    target = snapshots / ("65572b38d27c" + "0" * 52 + ".json")
    target.write_text("{}")
    assert locate_snapshot("65572b38d27c", snapshots) == target


def test_locate_snapshot_returns_none_when_missing(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    assert locate_snapshot("doesnotexist", snapshots) is None


def test_promote_snapshot_copies_to_manifest_path(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "abc", "cards": []}')
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)
    assert manifest.read_text() == snapshot.read_text()


def test_promote_snapshot_overwrites_existing_manifest(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "new"}')
    manifest = tmp_path / "latest.json"
    manifest.write_text('{"csv_sha256": "old"}')
    promote_snapshot(snapshot, manifest)
    assert "new" in manifest.read_text()
    assert "old" not in manifest.read_text()


def test_promote_snapshot_mirrors_to_build_manifest(tmp_path: Path) -> None:
    """The build-side mirror at web/src/data/manifest.json must also be
    updated, or Astro builds against a stale manifest and renamed-card
    pages don't ship — caught in production on 2026-05-12 evening."""
    # Recreate the conventional layout: <repo>/data/manifests/latest.json
    # and <repo>/web/src/data/manifest.json
    repo_root = tmp_path / "repo"
    pipeline = repo_root / "data" / "manifests"
    pipeline.mkdir(parents=True)
    build_dir = repo_root / "web" / "src" / "data"
    build_dir.mkdir(parents=True)

    snapshot = pipeline / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "new", "cards": []}')
    manifest = pipeline / "latest.json"
    promote_snapshot(snapshot, manifest)

    build_manifest = build_dir / "manifest.json"
    assert build_manifest.exists(), "build-side mirror must be created"
    assert build_manifest.read_text() == snapshot.read_text()


def test_promote_snapshot_skips_build_mirror_when_layout_absent(tmp_path: Path) -> None:
    """Promotion must still succeed when web/src/data/ doesn't exist
    (e.g., CLI-only checkouts without npm install)."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}")
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)  # must not raise
    assert manifest.read_text() == snapshot.read_text()


# --- Snapshot mirror to web/public/data/snapshots/ (the /diff page) ---


def _build_repo(tmp_path: Path) -> Path:
    """Recreate the conventional layout so promote_snapshot has all paths."""
    repo_root = tmp_path / "repo"
    (repo_root / "data" / "manifests").mkdir(parents=True)
    (repo_root / "web" / "src" / "data").mkdir(parents=True)
    (repo_root / "web" / "public" / "data" / "snapshots").mkdir(parents=True)
    return repo_root


def test_promote_snapshot_mirrors_to_web_snapshots_dir(tmp_path: Path) -> None:
    """Snapshot file appears at web/public/data/snapshots/<sha>.json so
    the /diff page can compare against it."""
    import json as _json
    repo_root = _build_repo(tmp_path)
    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text(_json.dumps({
        "csv_sha256": "abc123def456" + "0" * 52,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [],
    }))
    manifest = pipeline / "latest.json"
    promote_snapshot(snapshot, manifest)

    web_snapshots = repo_root / "web" / "public" / "data" / "snapshots"
    expected = web_snapshots / ("abc123def456" + "0" * 52 + ".json")
    assert expected.exists(), "snapshot must be mirrored to web-side"
    assert expected.read_text() == snapshot.read_text()


def test_promote_snapshot_rebuilds_web_snapshots_index(tmp_path: Path) -> None:
    """index.json reflects every snapshot on disk after promotion.

    The web index carries enriched ``{filename, fetched_at, card_count}``
    objects so the /diff selectors can label each snapshot (date + card
    count) without first lazily fetching its full manifest — otherwise
    every unselected option renders "?? cards".
    """
    import json as _json
    repo_root = _build_repo(tmp_path)
    web_snapshots = repo_root / "web" / "public" / "data" / "snapshots"
    # Pre-populate with a prior snapshot to ensure it stays in the index.
    prior_sha = "111" + "0" * 61
    prior = web_snapshots / f"{prior_sha}.json"
    prior.write_text(_json.dumps({
        "csv_sha256": prior_sha,
        "fetched_at": "2026-05-11T00:00:00Z",
        "cards": [],
    }))

    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    new_sha = "222" + "0" * 61
    snapshot.write_text(_json.dumps({
        "csv_sha256": new_sha,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [{"card_id": "a"}, {"card_id": "b"}],
    }))
    manifest = pipeline / "latest.json"
    promote_snapshot(snapshot, manifest)

    index_data = _json.loads((web_snapshots / "index.json").read_text())
    by_name = {e["filename"]: e for e in index_data}
    assert prior.name in by_name
    assert f"{new_sha}.json" in by_name
    # Enriched label metadata is present and correct.
    assert by_name[prior.name]["card_count"] == 0
    assert by_name[f"{new_sha}.json"]["card_count"] == 2
    assert by_name[f"{new_sha}.json"]["fetched_at"] == "2026-05-12T20:00:00Z"
    # Ordering: oldest fetched_at first, newest last (matches /diff convention).
    order = [e["filename"] for e in index_data]
    assert order.index(prior.name) < order.index(f"{new_sha}.json")


def test_promote_snapshot_skips_web_snapshots_when_dir_absent(tmp_path: Path) -> None:
    """No-op silently when web/public/data/snapshots/ doesn't exist."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"csv_sha256": "abc", "cards": []}')
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)
    assert manifest.read_text() == snapshot.read_text()


# --- Operator-local builders (posters + thumbs) invoked from ingest run ---


def _build_repo_with_scripts(tmp_path: Path) -> tuple[Path, Path]:
    """Like _build_repo but also creates scripts/ dir with stub builder files."""
    repo_root = _build_repo(tmp_path)
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir()
    # Touch the two builder scripts so the orchestrator can find them.
    (scripts_dir / "build_video_posters.py").write_text("#!/usr/bin/env python\n")
    (scripts_dir / "build_pdf_thumbs.py").write_text("#!/usr/bin/env python\n")
    return repo_root, scripts_dir


def test_promote_snapshot_invokes_operator_local_builders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After mirroring filesystem surfaces, promote_snapshot should run
    `build_video_posters.py` and `build_pdf_thumbs.py` if both scripts
    exist on disk. Both are idempotent + graceful-skip on missing local
    inputs (the 2026-05-12 plan made this explicit), so running them
    from the orchestrator can't make a fresh-checkout state worse.
    """
    import json as _json
    import subprocess

    repo_root, scripts_dir = _build_repo_with_scripts(tmp_path)
    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text(_json.dumps({
        "csv_sha256": "abc" + "0" * 61,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [],
    }))
    manifest = pipeline / "latest.json"

    invoked: list[list[str]] = []

    def _fake_run(cmd, *args, **kwargs):
        invoked.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    promote_snapshot(snapshot, manifest)

    # Both builders should have been invoked exactly once each. Don't
    # constrain the python executable form — sys.executable can be
    # `python3`, `python3.12`, or a full venv path; we care about the
    # script argument, not how the interpreter is spelled.
    invoked_flat = [arg for cmd in invoked for arg in cmd]
    assert any("build_video_posters.py" in s for s in invoked_flat), (
        f"build_video_posters.py not invoked. invoked={invoked}"
    )
    assert any("build_pdf_thumbs.py" in s for s in invoked_flat), (
        f"build_pdf_thumbs.py not invoked. invoked={invoked}"
    )


def test_promote_snapshot_tolerates_builder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a builder exits non-zero (rare; the scripts are designed to
    exit 0 even when inputs are missing), the orchestrator must NOT
    raise — promote_snapshot is the single source of truth for the
    manifest mirror, and a broken-builder shouldn't block that.
    """
    import json as _json
    import subprocess

    repo_root, scripts_dir = _build_repo_with_scripts(tmp_path)
    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text(_json.dumps({
        "csv_sha256": "def" + "0" * 61,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [],
    }))
    manifest = pipeline / "latest.json"

    def _fake_run(cmd, *args, **kwargs):
        # Pretend the builder crashed
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    # Must not raise even though the builders return non-zero.
    promote_snapshot(snapshot, manifest)
    # And the core mirror still happened.
    assert manifest.read_text() == snapshot.read_text()


def test_promote_snapshot_surfaces_builder_output_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A builder's stdout/stderr and non-zero exit code must be SURFACED
    (printed), not captured-and-discarded — a silently-swallowed exit code
    is how the orphaned-builder regression hid. Still no raise: promotion
    stands regardless of an operator-local builder's outcome.
    """
    import json as _json
    import subprocess

    repo_root, _ = _build_repo_with_scripts(tmp_path)
    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text(_json.dumps({
        "csv_sha256": "abc" + "0" * 61,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [],
    }))
    manifest = pipeline / "latest.json"

    def _fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="wrote payload\n", stderr="r2 mirror root not found\n"
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    promote_snapshot(snapshot, manifest)  # must not raise

    out = capsys.readouterr().out
    assert "wrote payload" in out, "builder stdout must be surfaced"
    assert "r2 mirror root not found" in out, "builder stderr must be surfaced"
    assert "1" in out and "exited" in out.lower(), "non-zero exit code must be surfaced"


def test_promote_snapshot_skips_builders_when_scripts_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh-checkout / partial-checkout case: no scripts/ dir → no-op,
    no raise. The orchestrator should NOT subprocess-invoke a builder
    that doesn't exist on disk."""
    import json as _json
    import subprocess

    repo_root = _build_repo(tmp_path)  # no scripts/ dir
    pipeline = repo_root / "data" / "manifests"
    snapshot = pipeline / "snapshot.json"
    snapshot.write_text(_json.dumps({
        "csv_sha256": "ghi" + "0" * 61,
        "fetched_at": "2026-05-12T20:00:00Z",
        "cards": [],
    }))
    manifest = pipeline / "latest.json"

    invoked: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, *a, **kw: (invoked.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0)),
    )
    promote_snapshot(snapshot, manifest)
    assert invoked == [], f"should not invoke any builder when scripts/ is absent, got {invoked}"


def test_promote_snapshot_handles_corrupt_snapshot_gracefully(tmp_path: Path) -> None:
    """Corrupt snapshot JSON shouldn't crash the manifest copy step."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("not valid json")
    manifest = tmp_path / "latest.json"
    promote_snapshot(snapshot, manifest)  # must not raise
    assert manifest.read_text() == snapshot.read_text()


# --- summarize_ingest_work ---


def test_summarize_no_new_content_minimal_work() -> None:
    """Tranches with no Class B and no Class C-approved-as-new are
    'metadata-only': just promote and rebuild deploy mirrors. No
    download/OCR/embed needed."""
    diff = {
        "renames_confirmed": [],
        "new_content": [],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [{"card_id": "abc", "diffs": []}] * 5,
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_download"] == []
    assert summary["needs_ocr"] == []
    assert summary["needs_embed"] == []
    assert summary["metadata_only"] is True


def test_summarize_class_b_new_content_needs_download_ocr_embed() -> None:
    """Class B (net-new content) needs the full pipeline."""
    diff = {
        "renames_confirmed": [],
        "new_content": [
            {"new_card_id": "newcard1", "title": "X", "asset_url": "https://x/a.pdf"},
            {"new_card_id": "newcard2", "title": "Y", "asset_url": None},
        ],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    # newcard1 has asset → all three stages; newcard2 (no asset) only manifest.
    assert "newcard1" in summary["needs_download"]
    assert "newcard1" in summary["needs_ocr"]
    assert "newcard1" in summary["needs_embed"]
    assert "newcard2" not in summary["needs_download"]
    assert summary["metadata_only"] is False


def test_summarize_restored_modified_flags_for_inspection() -> None:
    """A restored_modified entry doesn't need OCR/embed automatically;
    it needs operator inspection of what changed."""
    diff = {
        "renames_confirmed": [], "new_content": [], "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [
            {"new_card_id": "modcard", "new_asset_url": "https://x/m.pdf"},
        ],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_inspection"] == ["modcard"]
    assert "modcard" not in summary["needs_ocr"]
    assert "modcard" not in summary["needs_embed"]


def test_summarize_renames_dont_need_download() -> None:
    """Class A renames are byte-identical to existing archive entries.
    No new download/OCR/embed work."""
    diff = {
        "renames_confirmed": [
            {"old_card_id": "old1", "new_card_id": "new1",
             "byte_sha256": "ff" * 32},
        ],
        "new_content": [], "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "field_only_changes": [],
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_download"] == []
    assert summary["needs_ocr"] == []
    assert summary["needs_embed"] == []
    assert summary["metadata_only"] is True
