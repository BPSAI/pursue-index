"""An over-cap or unreadable bytes-dir file quarantines; it never crashes the diff."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from pursue_index import pdf_limits
from pursue_index.tranche_bytes import classify_bytes
from pursue_index.tranche_resave import _verified_path, bytes_dir_check


def _stage(tmp_path: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.pdf").write_bytes(data)
    return sha


def test_verified_path_never_calls_read_bytes(tmp_path, monkeypatch) -> None:
    sha = _stage(tmp_path, b"%PDF-1.4 small")
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("whole-file read"))
    assert _verified_path(tmp_path, sha) == tmp_path / f"{sha}.pdf"


def test_over_cap_candidate_is_unverified_without_a_read(tmp_path, monkeypatch, caplog) -> None:
    sha = _stage(tmp_path, b"x" * 64)
    monkeypatch.setattr(pdf_limits, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("whole-file read"))
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: pytest.fail("opened"))
    with caplog.at_level(logging.WARNING):
        assert _verified_path(tmp_path, sha) is None
    assert "file-size-cap" in caplog.text


def test_unreadable_candidate_is_unverified(tmp_path, monkeypatch) -> None:
    sha = _stage(tmp_path, b"%PDF-1.4 small")
    def boom(self, *a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "open", boom)
    assert _verified_path(tmp_path, sha) is None


def test_over_cap_pair_is_content_changed_not_an_exception(tmp_path, monkeypatch) -> None:
    old, new = tmp_path / "o.pdf", tmp_path / "n.pdf"
    old.write_bytes(b"a" * 64)
    new.write_bytes(b"b" * 64)
    monkeypatch.setattr(pdf_limits, "MAX_FILE_BYTES", 10)
    assert classify_bytes(old, new) == "content-changed"


def test_check_quarantines_when_a_candidate_is_over_cap(tmp_path, monkeypatch) -> None:
    old_sha, new_sha = _stage(tmp_path, b"o" * 64), _stage(tmp_path, b"n" * 64)
    monkeypatch.setattr(pdf_limits, "MAX_FILE_BYTES", 10)
    check = bytes_dir_check(tmp_path, {"old": [{"byte_sha256": old_sha}]})
    assert check("old", new_sha) is None
