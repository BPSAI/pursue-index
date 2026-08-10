"""Run orchestration + coverage gate for the transcribe stage.

``preflight_coverage`` compares eligible-vs-produced with zero spend — the
verify-before-spend gate the CLI runs by default (identical shape to
``vision.run.preflight_coverage``, T48.4). ``run_transcribe`` produces
sidecars for eligible items using injected ``transcribe_fn``/``probe_fn``
seams, so tests never hit AAI or a real audio file. Per-item failures are
skip-and-count: one bad card never aborts the run, but the report's
``missing``/``ok`` surface the shortfall.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.transcribe.client import TranscriptResult
from pursue_index.transcribe.eligibility import EligibleItem
from pursue_index.transcribe.run import (
    preflight_coverage,
    produced_card_ids,
    run_transcribe,
)


def _item(card_id: str) -> EligibleItem:
    return EligibleItem(card_id=card_id, title=f"T {card_id}", dvids_video_id="123")


def _fake_result(speakers: list[str] | None = None) -> TranscriptResult:
    return TranscriptResult(
        utterances=[{"speaker": "A", "text": "hi", "start": 0, "end": 100}],
        audio_duration_s=12.0,
        speakers=speakers or ["A"],
        multichannel=False,
        raw={},
    )


def _make_audio(audio_dir: Path, card_id: str) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / f"{card_id}.mp4").write_bytes(b"fake mp4")


# --- preflight_coverage / produced_card_ids -------------------------------


def test_preflight_reports_shortfall_without_spending(tmp_path: Path) -> None:
    report = preflight_coverage([_item("aud1")], tmp_path)
    assert not report.ok
    assert report.missing == {"aud1"}
    assert list(tmp_path.glob("*")) == []  # preflight never writes anything


def test_preflight_passes_when_covered(tmp_path: Path) -> None:
    card_dir = tmp_path / "aud1"
    card_dir.mkdir()
    (card_dir / "meta.json").write_text(json.dumps({"card_id": "aud1", "status": "ok"}))
    report = preflight_coverage([_item("aud1")], tmp_path)
    assert report.ok
    assert not report.missing


def test_produced_card_ids_ignores_failed_status(tmp_path: Path) -> None:
    card_dir = tmp_path / "aud1"
    card_dir.mkdir()
    (card_dir / "meta.json").write_text(json.dumps({"card_id": "aud1", "status": "failed"}))
    assert produced_card_ids(tmp_path, {"aud1"}) == set()


def test_produced_card_ids_ignores_malformed_meta(tmp_path: Path) -> None:
    card_dir = tmp_path / "aud1"
    card_dir.mkdir()
    (card_dir / "meta.json").write_text("not json")
    assert produced_card_ids(tmp_path, {"aud1"}) == set()


# --- run_transcribe --------------------------------------------------------


def test_run_transcribe_writes_sidecar_and_reports_full_coverage(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    out_dir = tmp_path / "ocr"
    _make_audio(audio_dir, "aud1")

    report = run_transcribe(
        [_item("aud1")], audio_dir, out_dir,
        transcribe_fn=lambda path, *, multichannel: _fake_result(),
        probe_fn=lambda path: False,
    )
    assert report.ok
    assert (out_dir / "aud1" / "meta.json").exists()


def test_run_transcribe_is_idempotent_skips_already_produced(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    out_dir = tmp_path / "ocr"
    _make_audio(audio_dir, "aud1")
    calls: list[str] = []

    def counting_transcribe(path: Path, *, multichannel: bool) -> TranscriptResult:
        calls.append(path.name)
        return _fake_result()

    run_transcribe(
        [_item("aud1")], audio_dir, out_dir,
        transcribe_fn=counting_transcribe, probe_fn=lambda path: False,
    )
    run_transcribe(
        [_item("aud1")], audio_dir, out_dir,
        transcribe_fn=counting_transcribe, probe_fn=lambda path: False,
    )
    assert calls == ["aud1.mp4"]  # second run skipped the already-produced card


def test_run_transcribe_skip_and_count_on_failure_never_aborts_run(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    out_dir = tmp_path / "ocr"
    _make_audio(audio_dir, "aud1")
    _make_audio(audio_dir, "aud2")

    def flaky_transcribe(path: Path, *, multichannel: bool) -> TranscriptResult:
        if path.name == "aud1.mp4":
            raise RuntimeError("AAI transcript failed: bad audio format")
        return _fake_result()

    report = run_transcribe(
        [_item("aud1"), _item("aud2")], audio_dir, out_dir,
        transcribe_fn=flaky_transcribe, probe_fn=lambda path: False,
    )
    assert not report.ok
    assert report.missing == {"aud1"}
    assert (out_dir / "aud2" / "meta.json").exists()
    assert not (out_dir / "aud1").exists()
    assert report.failed == [("aud1", "AAI transcript failed: bad audio format")]


def test_run_transcribe_skips_missing_audio_file_as_a_failure(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"  # never populated
    out_dir = tmp_path / "ocr"

    report = run_transcribe(
        [_item("aud1")], audio_dir, out_dir,
        transcribe_fn=lambda path, *, multichannel: _fake_result(),
        probe_fn=lambda path: False,
    )
    assert not report.ok
    assert report.missing == {"aud1"}


def test_run_transcribe_uses_probe_fn_to_set_multichannel(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    out_dir = tmp_path / "ocr"
    _make_audio(audio_dir, "aud1")
    captured: dict[str, object] = {}

    def capturing_transcribe(path: Path, *, multichannel: bool) -> TranscriptResult:
        captured["multichannel"] = multichannel
        return _fake_result()

    run_transcribe(
        [_item("aud1")], audio_dir, out_dir,
        transcribe_fn=capturing_transcribe, probe_fn=lambda path: True,
    )
    assert captured["multichannel"] is True
