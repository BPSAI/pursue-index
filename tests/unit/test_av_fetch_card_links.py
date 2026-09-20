"""``<card_id>`` links the fetch stage stages beside the DOD-named files.

The links live in ``<staging>/by-card/`` so the DOD-id matcher, which globs the
staging dir's top level, still sees only ``DOD_<id>.mp4`` files. The transcribe
stage reads them back through ``audio_path_for``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.av_fetch.fetch import fetch_one, fetch_worklist
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe.eligibility import audio_path_for, select_eligible
from tests.support.av_fetch_fakes import (
    _ASSET_BYTES,
    _AUD_PAGE_BODY,
    _VID_PAGE_BODY,
    FakeCard,
    _assets,
    _pages,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_URL_1 = "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/DOD_111688723.mp4"
_URL_2 = "https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111689232/DOD_111689232.mp4"


def _fetchers():
    page_fetch = _pages({"1006056": (200, _VID_PAGE_BODY), "1006119": (200, _AUD_PAGE_BODY)})
    asset_fetch = _assets({
        _URL_1: (200, "binary/octet-stream", _ASSET_BYTES),
        _URL_2: (200, "binary/octet-stream", _ASSET_BYTES + b"y"),
    })
    return page_fetch, asset_fetch


def _fetch_c1(tmp_path: Path):
    page_fetch, asset_fetch = _fetchers()
    return fetch_one(
        FakeCard("c1", "VID", "1006056"), tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch
    )


def test_card_link_is_staged_under_by_card_not_the_top_level(tmp_path: Path) -> None:
    item = _fetch_c1(tmp_path)

    assert item.status == "fetched"
    link = tmp_path / "by-card" / "c1.mp4"
    assert link.read_bytes() == _ASSET_BYTES
    assert not (tmp_path / "c1.mp4").exists()
    assert [p.name for p in tmp_path.glob("*.mp4")] == ["DOD_111688723.mp4"]


def test_card_link_is_hard_linked_or_a_symlink_to_the_dod_file(tmp_path: Path) -> None:
    _fetch_c1(tmp_path)
    dod, link = tmp_path / "DOD_111688723.mp4", tmp_path / "by-card" / "c1.mp4"
    if link.is_symlink():
        assert link.resolve() == dod.resolve()
    else:
        assert dod.stat().st_ino == link.stat().st_ino


def test_relinking_is_idempotent_and_relinks_an_already_staged_file(tmp_path: Path) -> None:
    assert _fetch_c1(tmp_path).status == "fetched"
    assert _fetch_c1(tmp_path).status == "skipped_existing"
    (tmp_path / "by-card" / "c1.mp4").unlink()
    assert _fetch_c1(tmp_path).status == "skipped_existing"
    assert (tmp_path / "by-card" / "c1.mp4").exists()


def test_a_dangling_card_link_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "by-card").mkdir()
    link = tmp_path / "by-card" / "c1.mp4"
    link.symlink_to("../DOD_gone.mp4")
    assert link.is_symlink() and not link.exists()

    assert _fetch_c1(tmp_path).status == "fetched"
    assert link.read_bytes() == _ASSET_BYTES


def test_a_working_card_link_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "by-card").mkdir()
    other = tmp_path / "DOD_other.mp4"
    other.write_bytes(b"existing")
    link = tmp_path / "by-card" / "c1.mp4"
    link.symlink_to("../DOD_other.mp4")

    assert _fetch_c1(tmp_path).status == "fetched"
    assert link.is_symlink()
    assert link.read_bytes() == b"existing"


def _aud(card_id: str, dvids: str, **over: object) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=card_id, asset_type="AUD", agency="NASA",
        dvids_video_id=dvids, release_date="2026-03-15", **over,
    )


def test_a_multi_row_card_gets_one_link_per_row_and_no_bare_name(tmp_path: Path) -> None:
    rows = [_aud("dup", "1006056"), _aud("dup", "1006119"), _aud("solo", "1006056")]
    page_fetch, asset_fetch = _fetchers()

    report = fetch_worklist(rows, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)

    assert report.ok
    names = sorted(p.name for p in (tmp_path / "by-card").iterdir())
    assert names == ["dup-1006056.mp4", "dup-1006119.mp4", "solo.mp4"]
    assert (tmp_path / "by-card" / "dup-1006119.mp4").read_bytes() == _ASSET_BYTES + b"y"


def test_audio_path_for_reads_the_links_fetch_stages(tmp_path: Path) -> None:
    rows = [_aud("dup", "1006056"), _aud("dup", "1006119"), _aud("solo", "1006056")]
    page_fetch, asset_fetch = _fetchers()
    fetch_worklist(rows, tmp_path, page_fetch=page_fetch, asset_fetch=asset_fetch)
    manifest = Manifest(
        source_url="https://x", fetched_at=datetime.now(UTC), csv_sha256="0" * 64, cards=rows
    )

    paths = {i.row_key: audio_path_for(i, tmp_path) for i in select_eligible(manifest, None)}

    assert paths["1006056"] == tmp_path / "by-card" / "dup-1006056.mp4"
    assert paths["1006119"] == tmp_path / "by-card" / "dup-1006119.mp4"
    assert paths[""] == tmp_path / "by-card" / "solo.mp4"
    assert all(p.is_file() for p in paths.values())


def test_release_video_ingest_dry_run_sees_no_file_without_a_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The DOD-id matcher globs the staging dir's top level; links must not show."""
    scripts = str(_REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import ingest_release_videos as ingest

    rows = [_aud("dup", "1006056"), _aud("dup", "1006119")]
    staging = tmp_path / "staging"
    page_fetch, asset_fetch = _fetchers()
    fetch_worklist(rows, staging, page_fetch=page_fetch, asset_fetch=asset_fetch)
    manifest = tmp_path / "manifest.json"
    save_manifest(
        Manifest(source_url="https://x", fetched_at=datetime.now(UTC), csv_sha256="0" * 64, cards=rows),
        manifest,
    )
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    dod = {"1006056": "DOD_111688723.mp4", "1006119": "DOD_111689232.mp4"}
    monkeypatch.setattr(ingest, "resolve_dod_filename", lambda card: dod[card.dvids_video_id])

    code = ingest.main([
        "--desktop", str(staging), "--manifest", str(manifest), "--env", str(env),
        "--release-date", "2026-03-15", "--dry-run",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert "0 files-without-card" in out
    assert "desktop MP4s: 2" in out
