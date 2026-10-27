"""``pursue transcribe asr-diff run`` -- dry-run cost preview only.

This command never calls a second engine; it always previews projected
cost. Smoke-tests argv parsing + eligible-row selection from committed
transcript meta.json fixtures, the same style as test_clean_qc_cli.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()


def _write_manifest(path: Path, card_ids: list[str]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[
            CardMetadata(
                card_id=cid, title=f"AUD {cid}", asset_type="AUD", agency="NASA",
                dvids_video_id="1006119",
            )
            for cid in card_ids
        ],
    )
    path.write_text(m.model_dump_json(by_alias=True))


def _write_transcript_meta(
    out_dir: Path, card_id: str, *, audio_duration_s: float, row_key: str = "",
) -> None:
    card_dir = out_dir / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(json.dumps({
        "card_id": card_id, "engine": "assemblyai", "status": "ok",
        "page_count": 1,
        "rows": [{"row_key": row_key, "audio_duration_s": audio_duration_s, "pages": 1}],
    }))


def test_dry_run_previews_cost_for_every_eligible_row_without_spending(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, ["a1a1a1a1a1a1a1a1", "a2a2a2a2a2a2a2a2"])
    out_dir = tmp_path / "ocr"
    _write_transcript_meta(out_dir, "a1a1a1a1a1a1a1a1", audio_duration_s=120.0)
    _write_transcript_meta(out_dir, "a2a2a2a2a2a2a2a2", audio_duration_s=60.0)

    result = runner.invoke(app, [
        "transcribe", "asr-diff", "run",
        "--manifest", str(manifest),
        "--out", str(out_dir),
        "--engine-b", "fake-engine-b",
        "--rate-usd-per-minute", "0.03",
    ])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "a1a1a1a1a1a1a1a1" in result.output and "a2a2a2a2a2a2a2a2" in result.output
    # 120s + 60s = 3 minutes total @ $0.03/min = $0.09
    assert "0.09" in result.output


def test_a_card_with_no_transcript_yet_is_not_eligible(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, ["a1a1a1a1a1a1a1a1"])
    out_dir = tmp_path / "ocr"  # no meta.json written: not yet transcribed

    result = runner.invoke(app, [
        "transcribe", "asr-diff", "run",
        "--manifest", str(manifest),
        "--out", str(out_dir),
        "--engine-b", "fake-engine-b",
        "--rate-usd-per-minute", "0.03",
    ])
    assert result.exit_code == 0, result.output
    assert "0 row" in result.output


def test_a_row_already_compared_under_the_same_engine_pair_is_excluded(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, ["a1a1a1a1a1a1a1a1"])
    out_dir = tmp_path / "ocr"
    _write_transcript_meta(out_dir, "a1a1a1a1a1a1a1a1", audio_duration_s=120.0)
    (out_dir / "a1a1a1a1a1a1a1a1" / "asr_diff.jsonl").write_text(json.dumps({
        "row_key": "", "engine_a": "assemblyai", "engine_b": "fake-engine-b",
        "status": "judged", "agreement": 1.0,
    }) + "\n")

    result = runner.invoke(app, [
        "transcribe", "asr-diff", "run",
        "--manifest", str(manifest),
        "--out", str(out_dir),
        "--engine-b", "fake-engine-b",
        "--rate-usd-per-minute", "0.03",
    ])
    assert result.exit_code == 0, result.output
    assert "0 row" in result.output
