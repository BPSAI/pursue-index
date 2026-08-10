"""``pursue transcribe run`` CLI surface.

Default run is the *verify-before-spend preflight*: it selects eligible AUD
items, diffs against produced sidecars, and exits non-zero on a coverage
shortfall — no AAI calls, no ffprobe. ``--live-smoke <card_id>`` is the ONLY
live path; here it is exercised with the client/probe seams monkeypatched so
the suite (and CI) never spends. A VID row is provably excluded from
eligibility by the shortfall test (only the AUD card is reported missing).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()


def _write_manifest(path: Path, cards: list[CardMetadata]) -> None:
    m = Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="0" * 64,
        cards=cards,
    )
    path.write_text(m.model_dump_json(by_alias=True))


def _aud_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"AUD {card_id}", asset_type="AUD", agency="NASA",
        dvids_video_id="1006119",
    )


def _vid_card(card_id: str) -> CardMetadata:
    return CardMetadata(
        card_id=card_id, title=f"VID {card_id}", asset_type="VID", agency="NASA",
        dvids_video_id="1006056",
    )


def test_preflight_exits_nonzero_on_shortfall_and_excludes_vid(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1"), _vid_card("vid1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--audio-dir", str(tmp_path / "audio"),
            "--out", str(tmp_path / "ocr"),
        ],
    )
    assert result.exit_code == 1
    assert "aud1" in result.stdout
    assert "vid1" not in result.stdout  # VID was never eligible, never reported


def test_preflight_passes_when_covered(tmp_path: Path) -> None:
    out = tmp_path / "ocr"
    card_dir = out / "aud1"
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"card_id": "aud1", "status": "ok"}))
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--audio-dir", str(tmp_path / "audio"),
            "--out", str(out),
        ],
    )
    assert result.exit_code == 0


def test_live_smoke_produces_single_sidecar(tmp_path: Path, monkeypatch) -> None:
    import pursue_index.transcribe.client as client_mod
    import pursue_index.transcribe.probe as probe_mod

    calls: list[str] = []

    def fake_transcribe_file(path, **_kw):
        calls.append(path.name)
        return client_mod.TranscriptResult(
            utterances=[{"speaker": "A", "text": "smoke", "start": 0, "end": 100}],
            audio_duration_s=1.0, speakers=["A"], multichannel=False, raw={},
        )

    monkeypatch.setattr(client_mod, "transcribe_file", fake_transcribe_file)
    monkeypatch.setattr(probe_mod, "is_stereo", lambda path, **kw: False)

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "aud1.mp4").write_bytes(b"fake mp4")
    (audio_dir / "aud2.mp4").write_bytes(b"fake mp4")

    out = tmp_path / "ocr"
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1"), _aud_card("aud2")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--audio-dir", str(audio_dir),
            "--out", str(out),
            "--live-smoke", "aud1",
        ],
    )
    assert result.exit_code == 0
    # Exactly one card transcribed (the smoke target), not the whole worklist.
    assert calls == ["aud1.mp4"]
    assert (out / "aud1" / "meta.json").exists()
    assert not (out / "aud2").exists()


def test_live_smoke_unknown_card_errors(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_aud_card("aud1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--audio-dir", str(tmp_path / "audio"),
            "--out", str(tmp_path / "ocr"),
            "--live-smoke", "ghost",
        ],
    )
    assert result.exit_code != 0


def test_live_smoke_vid_card_is_not_eligible(tmp_path: Path) -> None:
    """A VID card can never be reached via --live-smoke either."""
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_vid_card("vid1")])
    result = runner.invoke(
        app,
        [
            "transcribe", "run",
            "--manifest", str(manifest),
            "--audio-dir", str(tmp_path / "audio"),
            "--out", str(tmp_path / "ocr"),
            "--live-smoke", "vid1",
        ],
    )
    assert result.exit_code != 0
