"""Test for 'make bundle-copy' target that copies clean-qc-bundle.json."""

import json
import subprocess
from pathlib import Path

import pytest


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
    """bundle-copy should copy the bundle and print byte counts."""
    nas_root = tmp_path / "nas-root"
    nas_root.mkdir()

    # Create the published directory structure with a test bundle
    published_dir = nas_root / "published" / "v1"
    published_dir.mkdir(parents=True)

    bundle_content = {"qc": "test", "data": list(range(100))}
    source_bundle = published_dir / "clean-qc-bundle.json"
    source_bundle.write_text(json.dumps(bundle_content))

    source_bytes = len(source_bundle.read_bytes())

    # Create web/public/data directory if it doesn't exist
    web_data_dir = Path.cwd() / "web" / "public" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)

    # Set up environment
    env = {"PURSUE_DATA_ROOT": str(nas_root)}

    result = subprocess.run(
        ["make", "bundle-copy"],
        cwd=Path.cwd(),
        env={**dict(subprocess.os.environ), **env},
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, f"bundle-copy failed: {result.stderr}"

    # Check that the file was copied
    dest_bundle = web_data_dir / "clean-qc-bundle.json"
    assert dest_bundle.exists(), f"Bundle not copied to {dest_bundle}"

    # Verify content matches
    dest_content = json.loads(dest_bundle.read_text())
    assert dest_content == bundle_content, "Bundle content doesn't match"

    # Check that byte count was printed
    assert str(source_bytes) in result.stdout or str(source_bytes) in result.stderr, \
        f"Byte count {source_bytes} not printed in output"
