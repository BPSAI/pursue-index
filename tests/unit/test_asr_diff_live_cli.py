"""``pursue transcribe asr-diff live``: dry run by default, --confirm to run."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import asr_diff_live_cli
from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.transcribe import asr_diff_live
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.engine_b_parakeet import ENGINE_B_NAME

runner = CliRunner()
A, B = "a1" * 8, "b2" * 8


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    manifest = tmp_path / "m.json"
    manifest.write_text(Manifest(
        source_url="https://www.war.gov/uap-csv.csv", fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=[CardMetadata(card_id=c, title=f"AUD {c}", asset_type="AUD", agency="NASA")
               for c in (A, B)],
    ).model_dump_json(by_alias=True))
    ocr, audio = tmp_path / "ocr", tmp_path / "audio"
    for cid, dur in ((A, 120.0), (B, 60.0)):
        d = ocr / cid
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({
            "card_id": cid, "engine": "assemblyai", "status": "ok", "finished_at": "v1",
            "audio_duration_s": dur, "speakers": ["A", "B"],
        }))
        (d / "pages.jsonl").write_text(json.dumps(
            {"page": 1, "text": "Speaker A: Roger, I see it.\n\nSpeaker B: Copy that."}) + "\n")
    (audio / "by-card").mkdir(parents=True)
    (audio / "by-card" / f"{A}.mp4").write_bytes(b"x")
    # The staged audio's registered sha: the live pass only sends matching bytes.
    (tmp_path / "reg.jsonl").write_text(json.dumps(
        {"card_id": A, "byte_sha256": hashlib.sha256(b"x").hexdigest()}) + "\n")
    return manifest, ocr, audio


def _args(manifest: Path, ocr: Path, audio: Path, *extra: str) -> list[str]:
    return ["transcribe", "asr-diff", "live", "--manifest", str(manifest),
            "--out", str(ocr), "--audio-dir", str(audio),
            "--registry", str(manifest.parent / "reg.jsonl"), *extra]


@pytest.fixture
def no_model(monkeypatch):
    def refuse(_device):
        raise AssertionError("the dry run must not build the engine")
    monkeypatch.setattr(asr_diff_live_cli, "engine_factory", refuse)


def test_dry_run_loads_no_model_and_writes_nothing(tmp_path, no_model) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    result = runner.invoke(app, _args(manifest, ocr, audio))
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output and "2 pending" in result.output
    assert "3.0 min" in result.output  # 120 s + 60 s, read from top-level meta
    assert "$0.00" in result.output and ENGINE_B_NAME in result.output
    assert "--confirm" in result.output
    assert not list(ocr.glob(f"*/{sidecar.SIDECAR_FILE}"))


def test_without_confirm_the_engine_never_runs(tmp_path, no_model) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    result = runner.invoke(app, _args(manifest, ocr, audio))
    assert "Not started" in result.output


def test_confirm_runs_pending_rows_and_records_the_engine_name(tmp_path, monkeypatch) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    heard: list[Path] = []

    def fake_factory(device):
        assert device == "cuda"
        return lambda path: heard.append(path) or "Roger, I see it. Copy that."

    monkeypatch.setattr(asr_diff_live_cli, "engine_factory", fake_factory)
    result = runner.invoke(app, _args(manifest, ocr, audio, "--confirm"))
    assert result.exit_code == 0, result.output
    assert heard == [audio / "by-card" / f"{A}.mp4"]  # B has no staged audio
    assert "audio not staged" in result.output
    row = sidecar.load_existing(ocr / A / sidecar.SIDECAR_FILE)[""]
    assert row["engine_b"] == ENGINE_B_NAME and row["engine_a"] == "assemblyai"
    assert row["agreement"] == 1.0  # speaker labels are not compared as words
    assert "do not say which is right" in result.output


def test_a_compared_row_is_not_pending_again(tmp_path, monkeypatch) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    monkeypatch.setattr(asr_diff_live_cli, "engine_factory",
                        lambda _d: (lambda _p: "Roger, I see it. Copy that."))
    runner.invoke(app, _args(manifest, ocr, audio, "--confirm"))
    rows = asr_diff_live.plan_rows([(A, "", None), (B, "", None)], ocr, audio, ENGINE_B_NAME)
    assert [r.state for r in rows] == ["compared", "pending"]


def test_transcript_text_strips_speaker_labels(tmp_path) -> None:
    _, ocr, _ = _setup(tmp_path)
    meta = sidecar.read_meta(ocr / A)
    assert asr_diff_live.transcript_text(ocr / A, meta) == "Roger, I see it. Copy that."


def test_estimate_is_zero_cost_and_counts_pending_audio() -> None:
    rows = [asr_diff_live.LiveRow("c", "", "pending", 600.0),
            asr_diff_live.LiveRow("d", "", "compared", 60.0)]
    e = asr_diff_live.estimate(rows)
    assert e["cost_usd"] == 0.0 and e["pending"] == 1 and e["audio_min"] == 10.0
    assert e["runtime_min"] > 0 and e["peak_vram_gib"] > 0


def test_unstaged_audio_falls_back_to_the_registered_mirror_copy(tmp_path) -> None:
    _, ocr, audio = _setup(tmp_path)
    mirror = tmp_path / "r2-mirror"
    (mirror / "archive").mkdir(parents=True)
    (mirror / "archive" / "beef.mp4").write_bytes(b"12345")
    registry = tmp_path / "reg.jsonl"
    registry.write_text("\n".join(json.dumps(r) for r in (
        {"card_id": B, "archive_key": "archive/old.mp4", "byte_size": 9},
        {"card_id": B, "archive_key": "archive/beef.mp4", "byte_size": 5},
        {"card_id": A, "archive_key": "../escape.mp4", "byte_size": 1},
    )) + "\n")
    mirrored = asr_diff_live.mirror_audio(registry, mirror)
    assert mirrored == {B: mirror / "archive" / "beef.mp4"}
    rows = asr_diff_live.plan_rows([(A, "", None), (B, "", None)], ocr, audio, ENGINE_B_NAME, mirrored)
    assert rows[0].audio_path == audio / "by-card" / f"{A}.mp4"  # staged wins
    assert rows[1].audio_path == mirror / "archive" / "beef.mp4"


def test_a_mirror_copy_of_the_wrong_size_is_not_used(tmp_path) -> None:
    mirror = tmp_path / "r2-mirror"
    (mirror / "archive").mkdir(parents=True)
    (mirror / "archive" / "x.mp4").write_bytes(b"123")
    registry = tmp_path / "reg.jsonl"
    registry.write_text(json.dumps({"card_id": A, "archive_key": "archive/x.mp4", "byte_size": 4}) + "\n")
    assert asr_diff_live.mirror_audio(registry, mirror) == {}


def _engine_spy(monkeypatch) -> list:
    heard: list = []
    monkeypatch.setattr(asr_diff_live_cli, "engine_factory",
                        lambda _device: (lambda path: heard.append(path) or "Roger, I see it. Copy that."))
    return heard


def test_audio_that_does_not_match_its_registered_sha_never_reaches_the_engine(
        tmp_path, monkeypatch) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    (audio / "by-card" / f"{A}.mp4").write_bytes(b"substituted")  # same path, other bytes
    heard = _engine_spy(monkeypatch)
    result = runner.invoke(app, _args(manifest, ocr, audio, "--confirm"))
    assert heard == []
    assert "does not match the registry" in result.output


def test_audio_with_no_registered_sha_never_reaches_the_engine(tmp_path, monkeypatch) -> None:
    manifest, ocr, audio = _setup(tmp_path)
    (tmp_path / "reg.jsonl").write_text("")
    heard = _engine_spy(monkeypatch)
    result = runner.invoke(app, _args(manifest, ocr, audio, "--confirm"))
    assert heard == [] and "does not match the registry" in result.output
