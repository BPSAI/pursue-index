"""How ``pursue transcribe run`` is scoped, and why that is the scope it takes.

A tranche work list is written from rows that carry an ``asset_url``. AUD rows
carry none — their bytes come from a DVIDS page — so a work list can never name
an audio card, and scoping the stage that way would select nothing while
reporting full coverage. The stage therefore scopes by ``--release-date``, the
same field the A/V fetch stage uses to reach the same rows.

The first test drives the real work-list writer rather than a hand-built list,
so the property it pins is the one the pipeline actually produces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.ingest_run import summarize_ingest_work
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()

_RELEASE = "2026-08-01"


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True), encoding="utf-8")


def _aud_card(card_id: str, release_date: str = _RELEASE) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"AUD {card_id}", asset_type="AUD", agency="NASA",
        dvids_video_id="1006119", release_date=release_date,
    )


def test_the_tranche_work_list_writer_never_names_an_audio_card() -> None:
    diff = {
        "new_content": [
            {
                "new_card_id": "aud1",
                "asset_type": "AUD",
                "asset_url": None,
                "dvids_video_id": "1006119",
            },
            {
                "new_card_id": "pdf1",
                "asset_type": "PDF",
                "asset_url": "https://www.war.gov/a.pdf",
            },
        ],
        "restored_modified": [],
    }
    summary = summarize_ingest_work(diff)
    assert summary["needs_download"] == ["pdf1"]
    assert "aud1" not in summary["needs_download"]


def test_release_date_scopes_the_preflight_to_that_release(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(
        manifest, [_aud_card("aud1"), _aud_card("older", release_date="2026-05-12")]
    )
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--release-date", _RELEASE,
            "--out", str(tmp_path / "ocr"),
        ],
    )
    assert result.exit_code == 1
    assert "aud1" in result.stdout
    assert "older" not in result.stdout


def test_preflight_needs_no_audio_directory(tmp_path: Path) -> None:
    """The zero-spend preflight reads sidecars only, so it asks for no source."""
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--out", str(tmp_path / "ocr"),
        ],
    )
    assert result.exit_code == 1  # a shortfall, not a missing-argument error
    assert "aud1" in result.stdout


def test_a_live_smoke_without_an_audio_directory_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--out", str(tmp_path / "ocr"),
            "--live-smoke", "aud1",
        ],
    )
    assert result.exit_code == 2
