"""``tranche_resave._verified_path`` only builds a path from a real sha256."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pursue_index.tranche_resave import bytes_dir_check

NEW_SHA = "ab" * 32


@pytest.mark.parametrize("bad", ["../../etc/passwd", "../" + "a" * 61, "AB" * 32, "ab" * 31,
                                 "ab" * 32 + "\n", "a/b" + "0" * 61])
def test_malformed_sha_is_refused_before_any_path_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    reads: list[Path] = []
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self) or b"")
    check = bytes_dir_check(tmp_path, {"old": [{"byte_sha256": bad}]})
    assert check("old", bad) is None
    assert reads == []


def test_well_formed_sha_still_reaches_the_file(tmp_path: Path) -> None:
    data = b"%PDF-1.4 x"
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.pdf").write_bytes(data)
    from pursue_index.tranche_resave import _verified_path
    assert _verified_path(tmp_path, sha) == tmp_path / f"{sha}.pdf"
