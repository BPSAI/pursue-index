"""The per-row ASR-diff sidecar (``pursue_index.transcribe.asr_diff_sidecar``).

Lives next to the transcript it diffs -- the same card directory as
``pages.jsonl``/``meta.json``/``utterances.jsonl`` -- one JSON line per
``row_key``, mirroring ``clean.qc.sidecar``'s shape.
"""

from __future__ import annotations

from pathlib import Path

from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff import AsrDiffResult, DisagreeingSpan


def _result() -> AsrDiffResult:
    return AsrDiffResult(
        agreement=0.95,
        word_count_a=10,
        word_count_b=10,
        disagreeing_spans=[DisagreeingSpan("light", "flight", (5, 6), (5, 6))],
    )


def test_missing_sidecar_has_no_existing_rows(tmp_path: Path) -> None:
    assert sidecar.load_existing(tmp_path / "asr_diff.jsonl") == {}


def test_write_row_then_round_trips_through_load_existing(tmp_path: Path) -> None:
    path = tmp_path / "card-1" / sidecar.SIDECAR_FILE
    row = sidecar.build_row(
        row_key="", engine_a="assemblyai", engine_b="fake-engine-b",
        result=_result(), threshold=0.90, status="judged",
    )
    sidecar.write_row(path, row)
    loaded = sidecar.load_existing(path)
    assert loaded[""]["status"] == "judged"
    assert loaded[""]["agreement"] == 0.95
    assert loaded[""]["disagreeing_spans"][0]["a_text"] == "light"


def test_write_row_appends_rather_than_overwriting(tmp_path: Path) -> None:
    path = tmp_path / sidecar.SIDECAR_FILE
    sidecar.write_row(path, sidecar.build_row(
        row_key="a", engine_a="x", engine_b="y", result=_result(),
        threshold=0.9, status="judged",
    ))
    sidecar.write_row(path, sidecar.build_row(
        row_key="b", engine_a="x", engine_b="y", result=_result(),
        threshold=0.9, status="review",
    ))
    loaded = sidecar.load_existing(path)
    assert set(loaded) == {"a", "b"}
    assert loaded["b"]["status"] == "review"


def test_should_skip_when_engine_pair_is_unchanged() -> None:
    row = {"engine_a": "assemblyai", "engine_b": "fake-engine-b", "status": "judged"}
    assert sidecar.should_skip(row, engine_a="assemblyai", engine_b="fake-engine-b")


def test_should_not_skip_when_either_engine_changed() -> None:
    row = {"engine_a": "assemblyai", "engine_b": "fake-engine-b", "status": "judged"}
    assert not sidecar.should_skip(row, engine_a="assemblyai", engine_b="other-engine")
    assert not sidecar.should_skip(row, engine_a="other", engine_b="fake-engine-b")


def test_malformed_lines_are_tolerated(tmp_path: Path) -> None:
    path = tmp_path / sidecar.SIDECAR_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json\n\n" + '{"row_key": "a", "status": "judged"}\n')
    loaded = sidecar.load_existing(path)
    assert set(loaded) == {"a"}
