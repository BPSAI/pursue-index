"""``pursue av-fetch run`` CLI surface.

Fully mocked at the transport seam (``csv_fetcher.http_get``, same pattern as
``test_av_fetch_client.py``) — no live network call. Exercises: scoping by
release_date, ``--dry-run`` (no bytes written, no fetch calls), and the
non-zero-exit-on-shortfall contract (a fetch failure must not be silent).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.av_fetch import client as av_client
from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()

_VID_PAGE_BODY = (
    '<source src="/video/1006056.m3u8" type="application/x-mpegURL" />'
    '<source src="https://d34w7g4gy10iej.cloudfront.net/video/2605/DOD_111688723/'
    'DOD_111688723.mp4" type=\'video/mp4; codecs="avc1"\' />'
)
_ASSET_BYTES = b"\x00\x00\x00\x1cftypM4V " + b"x" * 100


class _FakeResponse:
    """Stands in for the streamed transport response the asset GET reads."""

    def __init__(
        self, status_code: int, *, text: str = "", content: bytes = b"", headers=None
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.url = None

    def iter_content(self, chunk_size: int = 8192):
        if self.content:
            yield self.content

    def close(self) -> None:
        return None


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True))


def _vid_card(card_id: str, dvids_id: str, release_date: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"VID {card_id}", asset_type="VID", agency="DOW",
        release_date=release_date, dvids_video_id=dvids_id,
    )


def _fake_get_factory(page_status: int = 200, asset_status: int = 200):
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        if "dvidshub.net" in url:
            return _FakeResponse(page_status, text=_VID_PAGE_BODY)
        return _FakeResponse(
            asset_status,
            content=_ASSET_BYTES,
            headers={"content-type": "binary/octet-stream"},
        )

    return fake_get


def test_dry_run_prints_scope_and_fetches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_vid_card("c1", "1006056", "6/12/26")])

    def fail_get(url: str, **kwargs: object) -> _FakeResponse:
        raise AssertionError("dry-run must not fetch")

    monkeypatch.setattr(av_client.csv_fetcher, "http_get", fail_get)

    result = runner.invoke(
        app,
        [
            "av-fetch", "run",
            "--manifest", str(manifest),
            "--release-date", "6/12/26",
            "--staging-dir", str(tmp_path / "staged"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "c1" in result.stdout
    assert not (tmp_path / "staged").exists()


def test_run_exits_zero_and_stages_file_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_vid_card("c1", "1006056", "6/12/26")])
    monkeypatch.setattr(av_client.csv_fetcher, "http_get", _fake_get_factory())

    staging_dir = tmp_path / "staged"
    result = runner.invoke(
        app,
        [
            "av-fetch", "run",
            "--manifest", str(manifest),
            "--release-date", "6/12/26",
            "--staging-dir", str(staging_dir),
        ],
    )

    assert result.exit_code == 0
    assert (staging_dir / "DOD_111688723.mp4").read_bytes() == _ASSET_BYTES


def test_run_exits_nonzero_on_shortfall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_vid_card("c1", "1006056", "6/12/26")])
    monkeypatch.setattr(
        av_client.csv_fetcher, "http_get", _fake_get_factory(page_status=404)
    )

    result = runner.invoke(
        app,
        [
            "av-fetch", "run",
            "--manifest", str(manifest),
            "--release-date", "6/12/26",
            "--staging-dir", str(tmp_path / "staged"),
        ],
    )

    assert result.exit_code == 1
    assert "c1" in result.stdout  # failure is reported, never silent


def test_run_scopes_to_release_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(
        manifest,
        [
            _vid_card("c1", "1006056", "6/12/26"),
            _vid_card("c2", "1006099", "5/22/26"),
        ],
    )

    def fail_get(url: str, **kwargs: object) -> _FakeResponse:
        raise AssertionError("out-of-scope card must not be fetched")

    monkeypatch.setattr(av_client.csv_fetcher, "http_get", fail_get)

    result = runner.invoke(
        app,
        [
            "av-fetch", "run",
            "--manifest", str(manifest),
            "--release-date", "1/1/00",
            "--staging-dir", str(tmp_path / "staged"),
        ],
    )

    assert result.exit_code == 0
    assert "total=0" in result.stdout
