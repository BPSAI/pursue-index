"""``diff_tranches`` demoting a Class C quarantine on byte evidence (R7C.12).

With a ``--bytes-dir`` (``resave_check``), a Class C candidate whose new
bytes are its matched old card's bytes plus a metadata-only incremental
update moves out of ``quarantined`` into ``renames_metadata_only``. Without
evidence -- no bytes-dir, a missing file, a file whose bytes do not hash to
its name, or a ``content-changed`` verdict -- the diff is exactly what it
was before this check existed.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tranche_diff  # noqa: E402

from pursue_index.tranche_resave import (  # noqa: E402
    RESAVE_BUCKET,
    RESAVE_METHOD,
    bytes_dir_check,
)
from tests.support.tranche_bytes_fakes import (  # noqa: E402
    build_base_pdf,
    content_changed_resave,
    metadata_only_resave,
)

OLD_ID, NEW_ID = "a0f6663169c21caf", "ff3939f95d878062"
NEW_URL = "https://x/d042-new.pdf"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _card(card_id: str, url: str, location: str) -> dict:
    return {"card_id": card_id, "title": "DOW-UAP-D042, Range Fouler Debrief",
            "asset_type": "PDF", "agency": "DOW", "incident_date": "8/31/20",
            "incident_location": location, "asset_filename": url.rsplit("/", 1)[1],
            "asset_url": url}


def _diff(old_bytes: bytes, new_bytes: bytes, bytes_dir: Path | None, files: dict) -> dict:
    """Run the D042-shaped diff; ``files`` maps sha -> bytes written."""
    if bytes_dir is not None:
        for name, data in files.items():
            (bytes_dir / f"{name}.pdf").write_bytes(data)
    registry = {OLD_ID: [{"card_id": OLD_ID, "byte_sha256": _sha(old_bytes)}]}
    return tranche_diff.diff_tranches(
        old_manifest={"csv_sha256": "old", "cards": [_card(OLD_ID, "https://x/d042.pdf", "Japan")]},
        new_manifest={"csv_sha256": "new", "cards": [_card(NEW_ID, NEW_URL, "Japan")]},
        registry=registry,
        fetch_byte_sha={NEW_URL: _sha(new_bytes)}.get,
        resave_check=bytes_dir_check(bytes_dir, registry),
    )


def _pair(kind: str = "metadata") -> tuple[bytes, bytes]:
    base = build_base_pdf()
    new = metadata_only_resave(base) if kind == "metadata" else content_changed_resave(base)
    return base.data, new


def test_metadata_only_resave_moves_to_rename_bucket(tmp_path: Path) -> None:
    old, new = _pair()
    diff = _diff(old, new, tmp_path, {_sha(old): old, _sha(new): new})
    assert diff["quarantined"] == []
    [row] = diff[RESAVE_BUCKET]
    assert (row["old_card_id"], row["new_card_id"]) == (OLD_ID, NEW_ID)
    assert row["byte_sha256"] == _sha(new)
    assert row["old_byte_sha256"] == _sha(old)
    assert row["verdict"] == "metadata-only"
    assert row["method"] == RESAVE_METHOD == "metadata-only-resave"
    assert row["new_asset_url"] == NEW_URL


def test_summary_counts_the_row_once_and_old_card_is_not_removed(tmp_path: Path) -> None:
    old, new = _pair()
    diff = _diff(old, new, tmp_path, {_sha(old): old, _sha(new): new})
    s = diff["summary"]
    assert (s["quarantined"], s[RESAVE_BUCKET], s["removed"]) == (0, 1, 0)
    assert diff["removed"] == []


def test_no_bytes_dir_is_identical_to_before(tmp_path: Path) -> None:
    old, new = _pair()
    diff = _diff(old, new, None, {})
    assert RESAVE_BUCKET not in diff and RESAVE_BUCKET not in diff["summary"]
    assert [q["new_card_id"] for q in diff["quarantined"]] == [NEW_ID]


def test_missing_file_leaves_the_quarantine_untouched(tmp_path: Path) -> None:
    old, new = _pair()
    assert _diff(old, new, tmp_path, {_sha(old): old}) == _diff(old, new, None, {})


def test_content_changed_or_misnamed_bytes_stay_quarantined(tmp_path: Path) -> None:
    old, new = _pair("content")
    baseline = _diff(old, new, None, {})
    assert _diff(old, new, tmp_path, {_sha(old): old, _sha(new): new}) == baseline
    meta_old, meta_new = _pair()
    (tmp_path / "x").mkdir()
    misnamed = {_sha(meta_old): meta_old, _sha(meta_new): meta_new + b"%tampered\n"}
    assert _diff(meta_old, meta_new, tmp_path / "x", misnamed) == _diff(
        meta_old, meta_new, None, {})
