"""Shared AUD row logic behind the ``asr-diff run`` preview and the ``asr-diff live`` plan."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.card_id import InvalidCardIdError
from pursue_index.cli import asr_diff_cli, asr_diff_live_cli
from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe import asr_diff_live
from pursue_index.transcribe.asr_diff_rows import aud_card_ids, row_duration

runner = CliRunner()
CID = "a1" * 8


def _manifest(tmp_path: Path, card_ids: list[str]) -> Path:
    path = tmp_path / "m.json"
    path.write_text(Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[CardMetadata(card_id=c, title=f"AUD {c}", asset_type="AUD", agency="NASA")
               for c in card_ids],
    ).model_dump_json(by_alias=True))
    return path


def _meta(tmp_path: Path, card_id: str, meta: dict) -> Path:
    card_dir = tmp_path / "ocr" / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(json.dumps(
        {"card_id": card_id, "engine": "assemblyai", "status": "ok", **meta}))
    return card_dir


def _preview(tmp_path: Path, manifest: Path, engine_b: str = "fake") -> str:
    result = runner.invoke(app, [
        "transcribe", "asr-diff", "run", "--manifest", str(manifest),
        "--out", str(tmp_path / "ocr"), "--engine-b", engine_b, "--rate-usd-per-minute", "1",
    ])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


# -- row 2: one duration fallback ------------------------------------------------

@pytest.mark.parametrize(("meta", "row", "want"), [
    ({"audio_duration_s": 90.0}, {}, 90.0),                                   # single-row, top level
    ({"audio_duration_s": 90.0, "rows": [{"audio_duration_s": 30.0}]},
     {"audio_duration_s": 30.0}, 30.0),                                       # row value wins
    ({"audio_duration_s": 90.0, "rows": [{"audio_duration_s": 0.0}]},
     {"audio_duration_s": 0.0}, 0.0),                                         # an explicit 0 is kept
    ({"audio_duration_s": 90.0, "rows": [{}, {}]}, {}, 0.0),                  # multi-row: no top-level fallback
    ({"rows": [{"audio_duration_s": 40.0}, {}]}, {"audio_duration_s": 40.0}, 40.0),
    ({}, {}, 0.0),                                                            # missing everywhere
    ({}, {"audio_duration_s": "n/a"}, 0.0),                                   # unreadable
    ({}, {"audio_duration_s": -5.0}, 0.0),                                    # negative clamps to 0
])
def test_row_duration(meta: dict, row: dict, want: float) -> None:
    assert row_duration(meta, row) == want


def test_preview_keeps_an_explicit_zero_row_duration(tmp_path: Path) -> None:
    """The old inline fallback read a row's 0.0 as missing and costed the top level."""
    _meta(tmp_path, CID, {"audio_duration_s": 600.0, "rows": [{"row_key": "", "audio_duration_s": 0.0}]})
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    assert "total projected $0.00" in out


def test_preview_survives_an_unreadable_duration(tmp_path: Path) -> None:
    _meta(tmp_path, CID, {"rows": [{"row_key": "", "audio_duration_s": "n/a"}]})
    out = _preview(tmp_path, _manifest(tmp_path, [CID]))
    assert "total projected $0.00" in out


def test_preview_and_live_plan_agree_on_durations(tmp_path: Path) -> None:
    cases = {"b1" * 8: {"audio_duration_s": 120.0},
             "b2" * 8: {"rows": [{"row_key": "", "audio_duration_s": 0.0}], "audio_duration_s": 60.0},
             "b3" * 8: {}}
    for cid, meta in cases.items():
        _meta(tmp_path, cid, meta)
    out = _preview(tmp_path, _manifest(tmp_path, list(cases)))
    plan = asr_diff_live.plan_rows([(c, "", None) for c in cases], tmp_path / "ocr",
                                   tmp_path / "audio", "fake")
    total_min = sum(r.duration_s for r in plan if r.state == "pending") / 60
    assert f"total projected ${total_min:.2f}" in out


# -- row 3: public row/card selection ------------------------------------------

def test_aud_card_ids_selects_aud_cards_and_honours_the_filter(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[CardMetadata(card_id="c1" * 8, title="a", asset_type="AUD", agency="NASA"),
               CardMetadata(card_id="c2" * 8, title="b", asset_type="VID", agency="NASA"),
               CardMetadata(card_id="c3" * 8, title="c", asset_type="AUD", agency="NASA")],
    ).model_dump_json(by_alias=True))
    assert aud_card_ids(path, None) == ["c1" * 8, "c3" * 8]
    assert aud_card_ids(path, f" {'c3' * 8} , {'c2' * 8},") == ["c3" * 8]
    with pytest.raises(InvalidCardIdError):
        aud_card_ids(path, "not-a-card")


def test_both_clis_use_the_public_selection() -> None:
    assert not hasattr(asr_diff_cli, "_aud_card_ids")
    assert not hasattr(asr_diff_live_cli, "_aud_card_ids")
    assert asr_diff_cli.aud_card_ids is aud_card_ids
    assert asr_diff_live_cli.aud_card_ids is aud_card_ids
