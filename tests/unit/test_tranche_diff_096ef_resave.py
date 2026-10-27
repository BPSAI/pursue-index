"""R7C.12 regression against the real Release-7 tranche 096ef2c0058a.

Without ``--bytes-dir`` -- and with a ``--bytes-dir`` holding nothing
usable -- ``scripts/tranche_diff.py``'s ``main()`` must reproduce the
committed receipt ``data/tranche-diffs/tranche-diff-096ef2c0058a.{json,md}``
byte for byte. Inputs are the receipt's own (``tests/support/tranche_096ef``);
network fetches return the byte shas the receipt recorded. Output goes to
``tmp_path`` -- the committed receipt is a permanent record and is only read.

The ``--bytes-dir`` end-to-end replay, as a real subprocess, is
``test_tranche_diff_096ef_e2e.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.support.tranche_096ef import (
    NEW_MANIFEST,
    OLD_MANIFEST,
    RECEIPT,
    REPO_ROOT,
    d042_new_url,
    receipt_shas,
    receipt_time_registry,
)
from tests.support.tranche_bytes_fakes import build_base_pdf

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tranche_diff


def _run_main(monkeypatch, tmp_path: Path, shas: dict, *extra: str) -> Path:
    out_dir = tmp_path / "out"
    registry = receipt_time_registry(tmp_path / "registry.jsonl")
    monkeypatch.setattr(tranche_diff, "_fetch_byte_sha_via_curl", shas.get)
    monkeypatch.setattr(sys, "argv", [
        "tranche_diff.py", "--old-manifest", str(OLD_MANIFEST),
        "--new-manifest", str(NEW_MANIFEST), "--registry", str(registry),
        "--out-dir", str(out_dir), *extra,
    ])
    assert tranche_diff.main() == 0
    return out_dir / "tranche-diff-096ef2c0058a"


def _assert_matches_receipt(written: Path) -> None:
    for suffix in (".json", ".md"):
        assert written.with_suffix(suffix).read_bytes() == RECEIPT.with_suffix(suffix).read_bytes()


def test_no_bytes_dir_reproduces_committed_receipt(monkeypatch, tmp_path: Path) -> None:
    _assert_matches_receipt(_run_main(monkeypatch, tmp_path, receipt_shas()))


@pytest.mark.parametrize("populate", [False, True], ids=["empty-dir", "misnamed-file"])
def test_unusable_bytes_dir_reproduces_committed_receipt(
    monkeypatch, tmp_path: Path, populate: bool,
) -> None:
    """D042's real old sha has no file; with ``populate``, a file sits under
    the new sha's name whose bytes do not hash to it."""
    bytes_dir = tmp_path / "bytes"
    bytes_dir.mkdir()
    shas = receipt_shas()
    if populate:
        (bytes_dir / f"{shas[d042_new_url()]}.pdf").write_bytes(build_base_pdf().data)
    _assert_matches_receipt(_run_main(
        monkeypatch, tmp_path, shas, "--bytes-dir", str(bytes_dir)))
