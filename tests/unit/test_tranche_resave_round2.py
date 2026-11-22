"""Round 2: ``old_cards`` is required, the module import order is safe, and the old asset
is selected once for the evidence check and the staged bytes alike."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _tranche_ready_job as ready_job  # noqa: E402

from pursue_index import tranche_resave  # noqa: E402
from pursue_index.tranche_manifest import display_rows_by_card_id  # noqa: E402
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave  # noqa: E402

CID = "0123456789abcdef"
PDF_URL, VID_URL = "https://www.war.gov/medialink/a.pdf", "https://www.dvidshub.net/video/1"
VID_SHA = "b" * 64


def _stage(tmp_path: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.pdf").write_bytes(data)
    return sha


def test_old_cards_is_required(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        tranche_resave.bytes_dir_check(tmp_path, {})  # type: ignore[call-arg]


def test_a_none_dir_still_means_no_check() -> None:
    assert tranche_resave.bytes_dir_check(None, {}, []) is None


@pytest.mark.parametrize("first", ["tranche_resave", "tranche_manifest", "tranche", "asset_rows"])
def test_each_module_imports_first_in_a_fresh_interpreter(first: str) -> None:
    others = ["tranche_resave", "tranche_manifest", "tranche"]
    code = "; ".join(f"import pursue_index.{m}" for m in [first, *others])
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def _two_asset_old_cards() -> list[dict]:
    """A video row listed BEFORE the pdf row, both under one card."""
    return [
        {"card_id": CID, "asset_type": "VID", "asset_url": VID_URL, "asset_filename": "1.mp4"},
        {"card_id": CID, "asset_type": "PDF", "asset_url": PDF_URL, "asset_filename": "a.pdf"},
    ]


def test_the_check_and_the_staged_bytes_use_the_same_old_asset(tmp_path, monkeypatch) -> None:
    base = build_base_pdf()
    old_sha = _stage(tmp_path, base.data)
    new_sha = _stage(tmp_path, metadata_only_resave(base))
    registry = {CID: [
        {"asset_url": PDF_URL, "asset_filename": "a.pdf", "byte_sha256": old_sha},
        {"asset_url": VID_URL, "asset_filename": "1.mp4", "byte_sha256": VID_SHA},
    ]}
    cards = _two_asset_old_cards()
    assert tranche_resave.bytes_dir_check(tmp_path, registry, cards)(CID, new_sha) == old_sha

    seen: list = []
    monkeypatch.setattr(ready_job, "stage_old", lambda url, sha, d: seen.append((url, sha)))
    monkeypatch.setattr(ready_job, "stage_new", lambda *_a: None)
    row = type("R", (), {"old_card_id": CID, "new_card_id": "n", "row": {}})()
    monkeypatch.setattr(ready_job.cands, "candidate_rows", lambda diff: [row])
    fetched = type("F", (), {"paths": {}})()
    ready_job._stage({}, display_rows_by_card_id(cards), registry, fetched, tmp_path)
    assert seen == [(PDF_URL, old_sha)]


def test_one_helper_selects_the_old_asset_for_both() -> None:
    cards = _two_asset_old_cards()
    registry = {CID: [{"asset_url": PDF_URL, "byte_sha256": "a" * 64},
                      {"asset_url": VID_URL, "byte_sha256": VID_SHA}]}
    by_id = display_rows_by_card_id(cards)
    assert tranche_resave.old_asset_sha(by_id, registry, CID) == "a" * 64
    assert tranche_resave.old_asset_sha(by_id, registry, "missing") is None
