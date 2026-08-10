"""What the transcribe coverage gate counts, and what it refuses to count.

Two properties are pinned here:

* Coverage is per eligible *row*. A card_id backed by two AUD rows needs both
  rows transcribed; one row's transcript never stands in for the other's.
* A call that returns no content is its own outcome. A transcript with no
  utterances leaves the row outstanding, so the gate still reports the
  shortfall rather than treating "the call returned" as "the row is covered".
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.pipeline import iter_card_pages
from pursue_index.transcribe.client import TranscriptResult
from pursue_index.transcribe.eligibility import EligibleItem, audio_path_for
from pursue_index.transcribe.run import preflight_coverage, run_transcribe


def _item(card_id: str, row_key: str = "") -> EligibleItem:
    return EligibleItem(
        card_id=card_id, title=f"T {card_id}", dvids_video_id="123", row_key=row_key
    )


def _result(utterances: list[dict[str, object]]) -> TranscriptResult:
    return TranscriptResult(
        utterances=utterances, audio_duration_s=12.0,
        speakers=["A"], multichannel=False, raw={},
    )


def _spoken(text: str) -> list[dict[str, object]]:
    return [{"speaker": "A", "text": text, "start": 0, "end": 100}]


def _stage_audio(audio_dir: Path, item: EligibleItem) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path_for(item, audio_dir).write_bytes(b"fake mp4")


def test_transcript_with_no_utterances_leaves_the_row_outstanding(
    tmp_path: Path,
) -> None:
    audio_dir, out_dir = tmp_path / "audio", tmp_path / "ocr"
    item = _item("aud1")
    _stage_audio(audio_dir, item)

    report = run_transcribe(
        [item], audio_dir, out_dir,
        transcribe_fn=lambda path, *, multichannel: _result([]),
        probe_fn=lambda path: False,
    )
    assert not report.ok
    assert report.missing == [("aud1", "")]
    assert report.empty == [("aud1", "")]


def test_an_empty_transcript_is_not_re_read_as_coverage_on_a_later_preflight(
    tmp_path: Path,
) -> None:
    audio_dir, out_dir = tmp_path / "audio", tmp_path / "ocr"
    item = _item("aud1")
    _stage_audio(audio_dir, item)
    run_transcribe(
        [item], audio_dir, out_dir,
        transcribe_fn=lambda path, *, multichannel: _result([]),
        probe_fn=lambda path: False,
    )
    assert not preflight_coverage([item], out_dir).ok


def test_one_row_of_a_shared_card_id_does_not_cover_the_other(
    tmp_path: Path,
) -> None:
    audio_dir, out_dir = tmp_path / "audio", tmp_path / "ocr"
    first, second = _item("dup", "1006119"), _item("dup", "1006120")
    _stage_audio(audio_dir, first)  # only the first row's bytes are staged

    report = run_transcribe(
        [first, second], audio_dir, out_dir,
        transcribe_fn=lambda path, *, multichannel: _result(_spoken("first row")),
        probe_fn=lambda path: False,
    )
    assert not report.ok
    assert report.missing == [("dup", "1006120")]


def test_both_rows_of_a_shared_card_id_land_in_the_one_card_directory(
    tmp_path: Path,
) -> None:
    audio_dir, out_dir = tmp_path / "audio", tmp_path / "ocr"
    first, second = _item("dup", "1006119"), _item("dup", "1006120")
    _stage_audio(audio_dir, first)
    _stage_audio(audio_dir, second)

    def transcribe_fn(path: Path, *, multichannel: bool) -> TranscriptResult:
        return _result(_spoken(f"from {path.stem}"))

    report = run_transcribe(
        [first, second], audio_dir, out_dir,
        transcribe_fn=transcribe_fn, probe_fn=lambda path: False,
    )
    assert report.ok
    meta = json.loads((out_dir / "dup" / "meta.json").read_text())
    assert [row["row_key"] for row in meta["rows"]] == ["1006119", "1006120"]

    pages = iter_card_pages(out_dir)
    assert [p.page for p in pages] == [1, 2]
    assert "from dup-1006119" in pages[0].text
    assert "from dup-1006120" in pages[1].text
