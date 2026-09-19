"""Transcript sidecar writer — the SAME ``ocr_dir/<card_id>/{pages.jsonl,
meta.json}`` consumption path OCR'd PDFs already use.

Inspected before writing this: ``ocr/pipeline.py`` (``_build_meta``/
``ocr_card`` write ``pages.jsonl`` rows shaped ``{page, text, confidence,
engine}`` and a ``meta.json`` gated on ``status == "ok"``) and
``embed/pipeline.py::iter_card_pages``/``embed/store.py::_read_card_pages``
(the ONLY consumer contract: a card directory needs ``meta.json["status"] ==
"ok"`` + ``pages.jsonl`` rows carrying ``page``/``text`` — nothing else is
required). Writing transcripts into this exact path makes an AUD card
full-text searchable/citable with ZERO changes to the embed/site consumption
code, matching the by-hand precedent in ``scripts/integrate_transcripts.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.embed.pipeline import iter_card_pages
from pursue_index.transcribe.client import TranscriptResult
from pursue_index.transcribe.eligibility import EligibleItem
from pursue_index.transcribe.pages import (
    build_pages_rows,
    paginate_utterances,
    write_transcript_sidecar,
)
from pursue_index.transcribe.run import looks_channel_duplicated, run_transcribe

_UTTERANCES = [
    {"speaker": "A", "text": "Houston, Tranquility Base here.", "start": 0, "end": 100},
    {"speaker": "A", "text": "The Eagle has landed.", "start": 100, "end": 200},
    {"speaker": "B", "text": "Roger, Tranquility.", "start": 200, "end": 300},
]


def test_paginate_utterances_merges_consecutive_same_speaker_turns() -> None:
    pages = paginate_utterances(_UTTERANCES, per_page=12)
    assert len(pages) == 1
    assert "Speaker A: Houston, Tranquility Base here. The Eagle has landed." in pages[0]
    assert "Speaker B: Roger, Tranquility." in pages[0]


def test_paginate_utterances_respects_per_page_grouping() -> None:
    pages = paginate_utterances(_UTTERANCES, per_page=2)
    assert len(pages) == 2


def test_build_pages_rows_shape_matches_ocr_pages_jsonl() -> None:
    rows = build_pages_rows(_UTTERANCES)
    assert rows[0]["page"] == 1
    assert rows[0]["engine"] == "assemblyai"
    assert rows[0]["confidence"] == 100.0
    assert "Speaker A" in rows[0]["text"]


def test_write_transcript_sidecar_writes_pages_jsonl_and_meta(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    n = write_transcript_sidecar(
        "aud1", out_dir, _UTTERANCES,
        multichannel=False, audio_duration_s=42.5, speakers=["A", "B"],
        source="aud1.mp4",
    )
    assert n == 1
    card_dir = out_dir / "aud1"
    assert (card_dir / "pages.jsonl").exists()
    meta = json.loads((card_dir / "meta.json").read_text())
    assert meta["status"] == "ok"
    assert meta["engine"] == "assemblyai"
    assert meta["card_id"] == "aud1"
    assert meta["page_count"] == 1
    assert meta["rows"] == [
        {
            "row_key": "",
            "source": "aud1.mp4",
            "multichannel": False,
            "audio_duration_s": 42.5,
            "speakers": ["A", "B"],
            "pages": 1,
        }
    ]

    rows = [json.loads(line) for line in (card_dir / "pages.jsonl").read_text().splitlines()]
    assert rows[0]["page"] == 1
    assert rows[0]["engine"] == "assemblyai"


def test_written_sidecar_is_read_unchanged_by_the_real_embed_loader(tmp_path: Path) -> None:
    """Round-trip through the ACTUAL consumption path — no mock of the reader."""
    out_dir = tmp_path / "ocr"
    write_transcript_sidecar(
        "aud1", out_dir, _UTTERANCES,
        multichannel=False, audio_duration_s=42.5, speakers=["A", "B"],
        source="aud1.mp4",
    )
    rows = iter_card_pages(out_dir)
    assert len(rows) == 1
    assert rows[0].card_id == "aud1"
    assert rows[0].page == 1
    assert "Speaker A" in rows[0].text


# --- channel-duplication guard (dual-mono regression) ----------------------


def _dual_mono_utterances(words: int = 40) -> list[dict]:
    """The dual-mono signature: every word arrives once per channel, as its own
    one-word utterance, so consecutive utterances repeat the same text."""
    out: list[dict] = []
    for i in range(words):
        for ch in ("1", "2"):
            out.append(
                {"speaker": ch, "text": f"word{i}", "start": i * 10, "end": i * 10 + 9,
                 "channel": ch}
            )
    return out


def test_looks_channel_duplicated_flags_one_word_per_utterance_duplicates() -> None:
    assert looks_channel_duplicated(_dual_mono_utterances()) is True


def test_looks_channel_duplicated_ignores_ordinary_diarized_transcript() -> None:
    utterances = [
        {"speaker": "A" if i % 2 == 0 else "B",
         "text": f"This is a full sentence number {i} spoken by someone.",
         "start": i, "end": i + 1}
        for i in range(40)
    ]
    assert looks_channel_duplicated(utterances) is False


def test_looks_channel_duplicated_ignores_one_word_utterances_without_repeats() -> None:
    utterances = [
        {"speaker": "A", "text": f"word{i}", "start": i, "end": i + 1} for i in range(40)
    ]
    assert looks_channel_duplicated(utterances) is False


def test_looks_channel_duplicated_ignores_a_short_transcript() -> None:
    """A brief exchange ("Yes." / "Yes.") is too little evidence to reject."""
    utterances = [
        {"speaker": "A", "text": "Yes", "start": 0, "end": 1},
        {"speaker": "B", "text": "Yes", "start": 1, "end": 2},
    ]
    assert looks_channel_duplicated(utterances) is False


def test_looks_channel_duplicated_false_for_no_utterances() -> None:
    assert looks_channel_duplicated([]) is False


def test_run_transcribe_rejects_a_channel_duplicated_transcript_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """Fail closed: the dual-mono shape is never written as sidecars, and the
    reason names the probe decision that led to it."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "aud1.mp4").write_bytes(b"fake mp4")
    out = tmp_path / "ocr"
    duplicated = TranscriptResult(
        utterances=_dual_mono_utterances(), audio_duration_s=60.0,
        speakers=["1", "2"], multichannel=True, raw={},
    )
    item = EligibleItem(card_id="aud1", title="T aud1", dvids_video_id="123")

    report = run_transcribe(
        [item], audio_dir, out,
        transcribe_fn=lambda path, **kw: duplicated,
        probe_fn=lambda path: True,
    )

    assert report.ok is False
    assert not (out / "aud1").exists()
    ((_, reason),) = report.failed
    assert "channel-duplicated" in reason
    assert "multichannel=True" in reason
