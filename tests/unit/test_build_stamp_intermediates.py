"""scripts/build_stamp.py: the optional ``intermediates`` key that pins the
release's intermediates archive to the stamp, so a check from git alone
covers the rebuild inputs too."""

from __future__ import annotations

import hashlib
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
    repo = tmp_path / "index"
    for rel, text in {"data/manifests/latest.json": "{}",
                      "web/public/data/pages.json": "[]"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


@pytest.fixture
def tarball(tmp_path: Path) -> Path:
    path = tmp_path / "dl" / "intermediates-v1.2.tar.gz"
    path.parent.mkdir()
    path.write_bytes(b"\x1f\x8b archive bytes")
    return path


def _stamp(repo: Path) -> dict:
    return json.loads((repo / build_stamp.STAMP_PATH).read_text())


def _write(repo: Path, *extra: str) -> dict:
    assert build_stamp.main(["write", "--root", str(repo), "--builder-commit", COMMIT,
                             *extra]) == 0
    return _stamp(repo)


def _verify(repo: Path, *extra: str) -> int:
    return build_stamp.main(["verify", "--root", str(repo), "--require", *extra])


def test_write_records_the_archive_name_and_sha(index: Path, tarball: Path) -> None:
    stamp = _write(index, "--intermediates", str(tarball))
    assert stamp["intermediates"] == {
        "name": "intermediates-v1.2.tar.gz",
        "sha256": hashlib.sha256(tarball.read_bytes()).hexdigest(),
    }
    # The name only: the stamp is published and never carries a local path.
    assert str(tarball.parent) not in (index / build_stamp.STAMP_PATH).read_text()


def test_write_refuses_a_file_not_named_like_the_archive(index: Path, tmp_path: Path) -> None:
    other = tmp_path / "payload.tar.gz"
    other.write_bytes(b"x")
    with pytest.raises(ValueError):
        build_stamp.main(["write", "--root", str(index), "--builder-commit", COMMIT,
                          "--intermediates", str(other)])


def test_verify_passes_on_the_stamped_archive(index: Path, tarball: Path) -> None:
    _write(index, "--intermediates", str(tarball))
    assert _verify(index, "--intermediates", str(tarball)) == 0
    assert _verify(index) == 0  # without the flag, as before


def test_verify_fails_on_a_one_byte_change_naming_both_shas(
        index: Path, tarball: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stamped = _write(index, "--intermediates", str(tarball))["intermediates"]["sha256"]
    data = bytearray(tarball.read_bytes())
    data[-1] ^= 1
    tarball.write_bytes(bytes(data))
    actual = hashlib.sha256(bytes(data)).hexdigest()
    capsys.readouterr()
    assert _verify(index, "--intermediates", str(tarball)) == 1
    err = capsys.readouterr().err
    assert stamped in err and actual in err


def test_verify_with_the_flag_fails_on_a_stamp_without_the_key(
        index: Path, tarball: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(index)
    capsys.readouterr()
    assert _verify(index, "--intermediates", str(tarball)) == 1
    assert "no intermediates" in capsys.readouterr().err


def test_verify_with_the_flag_fails_on_a_missing_tarball(index: Path, tarball: Path) -> None:
    _write(index, "--intermediates", str(tarball))
    tarball.unlink()
    assert _verify(index, "--intermediates", str(tarball)) == 1


def test_a_stamp_without_the_key_verifies_as_before(index: Path) -> None:
    stamp = _write(index)
    assert set(stamp) == {"schema", "builder_commit", "files"}
    assert build_stamp.problems(index, stamp) == []
    assert _verify(index) == 0


@pytest.mark.parametrize("bad", [
    "intermediates-v1.tar.gz",
    [],
    {"name": "intermediates-v1.tar.gz"},
    {"sha256": "0" * 64},
    {"name": "intermediates-v1.tar.gz", "sha256": "0" * 63},
    {"name": "intermediates-v1.tar.gz", "sha256": "A" * 64},
    {"name": "intermediates-v1.tar.gz", "sha256": int("1" * 64)},
    {"name": "intermediates-v1.tar.gz", "sha256": "0" * 64, "extra": 1},
    {"name": "payload.tar.gz", "sha256": "0" * 64},
    {"name": "intermediates-v1.zip", "sha256": "0" * 64},
    {"name": "../intermediates-v1.tar.gz", "sha256": "0" * 64},
    {"name": "x/intermediates-v1.tar.gz", "sha256": "0" * 64},
    {"name": "intermediates-a/b.tar.gz", "sha256": "0" * 64},
    {"name": "intermediates-.tar.gz", "sha256": "0" * 64},
    {"name": 5, "sha256": "0" * 64},
])
def test_a_malformed_key_fails_verify_without_the_flag(index: Path, bad: object) -> None:
    stamp = _write(index)
    stamp["intermediates"] = bad
    assert build_stamp.problems(index, stamp)
    (index / build_stamp.STAMP_PATH).write_text(json.dumps(stamp))
    assert _verify(index) == 1


def test_main_s_committed_stamp_still_verifies() -> None:
    # Every stamp committed before the key existed lacks it and must stay valid.
    stamp = json.loads((ROOT / build_stamp.STAMP_PATH).read_text())
    assert build_stamp.intermediates_problems(stamp) == []


def test_verify_with_the_flag_fails_without_any_stamp(index: Path, tarball: Path) -> None:
    # Not yet required or not, the reader asked for a check that cannot be made.
    assert build_stamp.main(["verify", "--root", str(index),
                             "--intermediates", str(tarball)]) == 1
