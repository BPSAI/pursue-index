"""Pre-commit check on the CSV bytes the poll workflow commits to main."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import verify_csv_artifact as v  # noqa: E402


def _put(tmp_path: Path, body: bytes) -> str:
    sha = hashlib.sha256(body).hexdigest()
    (tmp_path / f"{sha}.csv").write_bytes(body)
    return sha


def test_matching_small_file_passes(tmp_path: Path) -> None:
    sha = _put(tmp_path, b"Title\r\nA\r\n")
    assert v.verify(tmp_path, sha) is None


def test_oversize_file_is_refused(tmp_path: Path) -> None:
    sha = _put(tmp_path, b"x" * (v.MAX_CSV_BYTES + 1))
    reason = v.verify(tmp_path, sha)
    assert reason is not None and "size" in reason


def test_bytes_not_matching_registry_sha_are_refused(tmp_path: Path) -> None:
    wanted = "a" * 64
    (tmp_path / f"{wanted}.csv").write_bytes(b"other bytes")
    reason = v.verify(tmp_path, wanted)
    assert reason is not None and "sha" in reason


def test_missing_file_is_refused(tmp_path: Path) -> None:
    assert v.verify(tmp_path, "b" * 64) is not None


@pytest.mark.parametrize("bad", ["../x", "abc", "A" * 64, ""])
def test_malformed_sha_never_builds_a_path(tmp_path: Path, bad: str) -> None:
    assert v.verify(tmp_path, bad) is not None


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sha = _put(tmp_path, b"ok")
    assert v.main(["--dir", str(tmp_path), sha]) == 0
    assert v.main(["--dir", str(tmp_path), "c" * 64]) == 1
    assert "skip" in capsys.readouterr().out
