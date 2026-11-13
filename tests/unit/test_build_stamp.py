"""scripts/build_stamp.py: the promote bundle's digest record."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_stamp  # noqa: E402

COMMIT = "a" * 40


@pytest.fixture
def index(tmp_path: Path) -> Path:
    """A tiny pursue-index-shaped git checkout with bundle and non-bundle files."""
    repo = tmp_path / "index"
    files = {
        "data/manifests/latest.json": "{}",
        "data/card-aliases.json": "[]",
        "web/public/data/pages.json": "[]",
        "web/public/llms.txt": "llms",
        "web/src/data/cards.json": "{}",
        "web/src/data/types.ts": "export type X = 1;",  # code: not bundle
        "web/src/content/finds/a.mdx": "# find",  # editorial: not bundle
        "README.md": "readme",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _write(repo: Path) -> dict:
    assert build_stamp.main(["write", "--root", str(repo), "--builder-commit", COMMIT]) == 0
    return json.loads((repo / build_stamp.STAMP_PATH).read_text())


def test_the_bundle_is_tracked_data_only(index: Path) -> None:
    assert build_stamp.bundle_files(index) == [
        "data/card-aliases.json",
        "data/manifests/latest.json",
        "web/public/data/pages.json",
        "web/public/llms.txt",
        "web/src/data/cards.json",
    ]


def test_a_fresh_stamp_verifies(index: Path) -> None:
    stamp = _write(index)
    assert stamp["schema"] == build_stamp.SCHEMA and stamp["builder_commit"] == COMMIT
    assert build_stamp.problems(index, stamp) == []
    assert build_stamp.main(["verify", "--root", str(index)]) == 0


def test_an_edited_missing_or_unstamped_file_fails(index: Path) -> None:
    stamp = _write(index)
    (index / "web/public/data/pages.json").write_text("[1]")
    (index / "data/card-aliases.json").unlink()
    (index / "web/public/data/new.json").write_text("{}")
    subprocess.run(["git", "-C", str(index), "add", "web/public/data/new.json"], check=True)
    assert build_stamp.problems(index, stamp) == [
        "missing: data/card-aliases.json",
        "changed since the build: web/public/data/pages.json",
        "not in the stamp: web/public/data/new.json",
    ]
    assert build_stamp.main(["verify", "--root", str(index)]) == 1


def test_no_stamp_passes_unless_required(index: Path) -> None:
    assert build_stamp.main(["verify", "--root", str(index)]) == 0
    assert build_stamp.main(["verify", "--root", str(index), "--require"]) == 1


def test_a_malformed_stamp_fails(index: Path) -> None:
    good = _write(index)
    # A 40-digit JSON number would pass the sha regex once stringified
    # (connector P2 on dd7f437); the commit must be a JSON string.
    for bad in ({**good, "schema": "other"}, {**good, "builder_commit": "main"},
                {**good, "builder_commit": int("1" * 40)},
                {**good, "files": []}):
        assert build_stamp.problems(index, bad), bad


def test_the_builder_commit_must_be_a_sha(index: Path) -> None:
    with pytest.raises(ValueError):
        build_stamp.build(index, "HEAD")


def test_the_stamp_names_no_repository_or_path(index: Path) -> None:
    # The stamp is published with the content: it carries hashes and the
    # builder commit only: no repository name and no absolute or internal path.
    _write(index)
    text = (index / build_stamp.STAMP_PATH).read_text()
    stamp = json.loads(text)
    assert set(stamp) == {"schema", "builder_commit", "files"}
    assert str(index) not in text and not any(k.startswith("/") for k in stamp["files"])


@pytest.mark.parametrize("key", ["../../etc/passwd", "/etc/passwd", "data/manifests/../../x",
                                 "data/manifests/./a.json", "README.md", "web/src/data/types.ts",
                                 "web/public/data\\x", "data/manifests//a.json", ""])
def test_a_stamp_key_outside_the_bundle_is_refused_unread(index: Path, key: str) -> None:
    # Native review P1: a crafted key must never make verify read a file
    # outside the checkout (or outside the bundle).
    stamp = _write(index)
    stamp["files"][key] = "0" * 64
    assert f"not a bundle path: {key!r}" in build_stamp.problems(index, stamp)


def test_a_symlinked_bundle_file_is_refused(index: Path, tmp_path: Path) -> None:
    stamp = _write(index)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    target = index / "web/public/data/pages.json"
    target.unlink()
    target.symlink_to(outside)
    assert "symlink, not a file: web/public/data/pages.json" in build_stamp.problems(index, stamp)
    with pytest.raises(ValueError):
        build_stamp.build(index, COMMIT)


def test_only_the_two_named_code_files_are_excluded(index: Path) -> None:
    # Native review P2 on the verifier: a .ts suffix alone must not exempt a
    # file under a bundle root from the stamp.
    stamp = _write(index)
    (index / "web/public/data/sneaky.ts").write_text("x")
    subprocess.run(["git", "-C", str(index), "add", "web/public/data/sneaky.ts"], check=True)
    assert "not in the stamp: web/public/data/sneaky.ts" in build_stamp.problems(index, stamp)


def test_a_symlinked_parent_directory_is_refused(index: Path, tmp_path: Path) -> None:
    # Native review P2: a bundle file reached through a symlinked directory
    # resolves outside the checkout.
    stamp = _write(index)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "pages.json").write_text("[]")
    data = index / "web/public/data"
    (data / "pages.json").unlink()
    data.rmdir()
    data.symlink_to(outside, target_is_directory=True)
    assert "symlink, not a file: web/public/data/pages.json" in build_stamp.problems(index, stamp)
