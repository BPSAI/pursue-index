"""Test for 'make bundle-copy' target that copies clean-qc-bundle.json."""

import json
import subprocess
from pathlib import Path


def test_bundle_copy_requires_nas_root(tmp_path: Path) -> None:
    """bundle-copy should fail when PURSUE_DATA_ROOT is not set."""
    result = subprocess.run(
        ["make", "bundle-copy"],
        cwd=Path.cwd(),
        env={"PURSUE_DATA_ROOT": ""},  # explicitly unset
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "bundle-copy should fail without PURSUE_DATA_ROOT"


def test_bundle_copy_fails_when_source_missing(tmp_path: Path) -> None:
    """bundle-copy should fail when the source bundle doesn't exist."""
    nas_root = tmp_path / "nas-root"
    nas_root.mkdir()

    # Create the published directory structure but no bundle file
    (nas_root / "published" / "v1").mkdir(parents=True)

    # Set up environment with non-existent bundle
    env = {"PURSUE_DATA_ROOT": str(nas_root)}

    result = subprocess.run(
        ["make", "bundle-copy"],
        cwd=Path.cwd(),
        env={**dict(subprocess.os.environ), **env},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "bundle-copy should fail when source is missing"


def test_bundle_copy_copies_file_and_prints_bytes(tmp_path: Path) -> None:
    """bundle-copy should copy the bundle and print byte counts.

    The copy targets a temporary destination through ``BUNDLE_DEST`` so the
    tracked bundle under ``web/public/data`` is never touched by the suite.
    """
    nas_root = tmp_path / "nas-root"
    nas_root.mkdir()

    # Create the published directory structure with a test bundle
    published_dir = nas_root / "published" / "v1"
    published_dir.mkdir(parents=True)

    bundle_content = {"qc": "test", "data": list(range(100))}
    source_bundle = published_dir / "clean-qc-bundle.json"
    source_bundle.write_text(json.dumps(bundle_content))

    source_bytes = len(source_bundle.read_bytes())

    tracked = Path.cwd() / "web" / "public" / "data" / "clean-qc-bundle.json"
    tracked_before = tracked.read_bytes() if tracked.exists() else None
    dest_bundle = tmp_path / "out" / "clean-qc-bundle.json"

    env = {"PURSUE_DATA_ROOT": str(nas_root), "BUNDLE_DEST": str(dest_bundle)}

    try:
        result = subprocess.run(
            ["make", "bundle-copy"],
            cwd=Path.cwd(),
            env={**dict(subprocess.os.environ), **env},
            capture_output=True,
            text=True,
        )
    finally:
        # Put the tracked file back if an ignored override let the copy hit it.
        if tracked_before is not None and tracked.read_bytes() != tracked_before:
            tracked.write_bytes(tracked_before)
            tracked_clobbered = True
        else:
            tracked_clobbered = False

    assert not tracked_clobbered, "bundle-copy overwrote the tracked bundle"
    assert result.returncode == 0, f"bundle-copy failed: {result.stderr}"

    # Check that the file was copied to the override destination
    assert dest_bundle.exists(), f"Bundle not copied to {dest_bundle}"

    # Verify content matches
    dest_content = json.loads(dest_bundle.read_text())
    assert dest_content == bundle_content, "Bundle content doesn't match"

    # Check that byte count was printed
    assert str(source_bytes) in result.stdout or str(source_bytes) in result.stderr, \
        f"Byte count {source_bytes} not printed in output"

    # The tracked bundle is byte-identical to what it was before the run
    after = tracked.read_bytes() if tracked.exists() else None
    assert after == tracked_before


def _stage_versions(nas_root: Path, versions: dict[str, str | None]) -> None:
    for name, payload in versions.items():
        v_dir = nas_root / "published" / name
        v_dir.mkdir(parents=True)
        if payload is not None:
            (v_dir / "clean-qc-bundle.json").write_text(payload, encoding="utf-8")


def _bundle_copy(nas_root: Path, dest: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parent.parent.parent
    return subprocess.run(
        ["make", "bundle-copy"],
        cwd=repo_root,
        env={**dict(subprocess.os.environ), "PURSUE_DATA_ROOT": str(nas_root), "BUNDLE_DEST": str(dest)},
        capture_output=True,
        text=True,
    )


def test_bundle_copy_picks_the_highest_version_numerically(tmp_path: Path) -> None:
    """v10 is newer than v2, though it sorts before it as text."""
    nas_root = tmp_path / "nas-root"
    _stage_versions(nas_root, {"v1": '"one"', "v2": '"two"', "v10": '"ten"'})
    dest = tmp_path / "out" / "bundle.json"

    result = _bundle_copy(nas_root, dest)

    assert result.returncode == 0, result.stdout + result.stderr
    assert dest.read_text(encoding="utf-8") == '"ten"'
    assert "published/v10/" in result.stdout


def test_bundle_copy_fails_rather_than_use_an_older_version(tmp_path: Path) -> None:
    """The newest version lacking a bundle is an error, not a reason to ship v2's."""
    nas_root = tmp_path / "nas-root"
    _stage_versions(nas_root, {"v2": '"two"', "v10": None})
    dest = tmp_path / "bundle.json"

    result = _bundle_copy(nas_root, dest)

    assert result.returncode != 0
    assert not dest.exists()
