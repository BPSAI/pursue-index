"""The tranche path compares each asset with its own registry rows.

A card can be backed by a PDF row plus video rows whose bytes live on another
host. The registry's newest row for the card may be the video; the three
tranche sites must compare a PDF with the PDF's rows (same ``asset_url``, else
the newest earlier row of the same file type) and treat an asset with neither
as net-new -- the rule the archive path uses.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _tranche_classify as classify  # noqa: E402
import _tranche_ready_job as ready_job  # noqa: E402

from pursue_index.asset_rows import file_type, rows_of_asset  # noqa: E402
from pursue_index.tranche_resave import bytes_dir_check  # noqa: E402
from tests.support.tranche_bytes_fakes import (  # noqa: E402
    build_base_pdf,
    metadata_only_resave,
)

CID = "0123456789abcdef"
PDF_URL = "https://www.war.gov/medialink/a.pdf"
MOVED_PDF_URL = "https://www.war.gov/medialink/moved/a.pdf"
VID_URL = "https://www.dvidshub.net/video/1"
PDF_SHA, VID_SHA, OTHER_SHA = "a" * 64, "b" * 64, "c" * 64


def _row(url: str, name: str, sha: str, when: str) -> dict:
    return {"card_id": CID, "asset_url": url, "asset_filename": name,
            "byte_sha256": sha, "fetched_at": when}


# The video row is the card's NEWEST row, so a per-card ``rows[-1]`` reads it.
TWO_ASSETS = [
    _row(PDF_URL, "a.pdf", PDF_SHA, "2026-05-01T00:00:00+00:00"),
    _row(VID_URL, "1.mp4", VID_SHA, "2026-06-01T00:00:00+00:00"),
]


def _pdf_card(url: str = PDF_URL) -> dict:
    return {"card_id": CID, "title": "T", "asset_type": "PDF",
            "asset_url": url, "asset_filename": url.rsplit("/", 1)[1]}


def _classify(sha: str | None, url: str = PDF_URL, rows: list | None = None):
    return classify._classify_added_card(
        CID, _pdf_card(url), sha, {}, [], {CID: TWO_ASSETS if rows is None else rows})


def test_the_helper_lives_in_src_with_the_archive_rule() -> None:
    assert file_type("A.PDF", None) == ".pdf"
    assert rows_of_asset(TWO_ASSETS, PDF_URL) == [TWO_ASSETS[0]]
    assert rows_of_asset(TWO_ASSETS, MOVED_PDF_URL, "a.pdf") == [TWO_ASSETS[0]]
    assert rows_of_asset(TWO_ASSETS, "https://x/new.docx") == []


def test_restoration_compares_the_pdf_with_its_pdf_row() -> None:
    label, row = _classify(PDF_SHA)
    assert label == "RESTORED_UNCHANGED"
    assert row["pinned_byte_sha256"] == PDF_SHA
    assert row["pinned_fetched_at"] == "2026-05-01T00:00:00+00:00"


def test_restoration_flags_a_changed_pdf_against_the_pdf_row_not_the_video() -> None:
    label, row = _classify(OTHER_SHA)
    assert label == "RESTORED_MODIFIED"
    assert row["pinned_byte_sha256"] == PDF_SHA


def test_a_moved_pdf_falls_back_to_the_newest_pdf_row() -> None:
    label, row = _classify(PDF_SHA, url=MOVED_PDF_URL)
    assert (label, row["pinned_byte_sha256"]) == ("RESTORED_UNCHANGED", PDF_SHA)


def test_a_pdf_with_only_a_video_row_is_net_new_not_restored() -> None:
    label, _ = _classify(OTHER_SHA, rows=[TWO_ASSETS[1]])
    assert label == "B"


def _stage(tmp_path: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.pdf").write_bytes(data)
    return sha


def _old_cards() -> list[dict]:
    return [_pdf_card()]


def test_resave_check_reads_the_old_pdf_rows_not_the_video(tmp_path: Path) -> None:
    base = build_base_pdf()
    old_sha = _stage(tmp_path, base.data)
    new_sha = _stage(tmp_path, metadata_only_resave(base))
    registry = {CID: [{**TWO_ASSETS[0], "byte_sha256": old_sha}, TWO_ASSETS[1]]}
    check = bytes_dir_check(tmp_path, registry, _old_cards())
    assert check(CID, new_sha) == old_sha


def test_resave_check_without_a_row_for_the_old_asset_finds_no_evidence(tmp_path: Path) -> None:
    base = build_base_pdf()
    new_sha = _stage(tmp_path, metadata_only_resave(base))
    registry = {CID: [{**TWO_ASSETS[1], "byte_sha256": _stage(tmp_path, base.data)}]}
    assert bytes_dir_check(tmp_path, registry, _old_cards())(CID, new_sha) is None


def test_ready_job_stages_the_old_pdf_row(monkeypatch, tmp_path: Path) -> None:
    seen: list = []
    monkeypatch.setattr(ready_job, "stage_old", lambda url, sha, d: seen.append((url, sha)))
    monkeypatch.setattr(ready_job, "stage_new", lambda *_a: None)
    monkeypatch.setattr(ready_job.cands, "candidate_rows",
                        lambda diff: [type("R", (), {"old_card_id": CID, "new_card_id": "n",
                                                     "row": {}})()])
    fetched = type("F", (), {"paths": {}})()
    ready_job._stage({}, {CID: _pdf_card()}, {CID: TWO_ASSETS}, fetched, tmp_path)
    assert seen == [(PDF_URL, PDF_SHA)]
