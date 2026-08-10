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
from pursue_index.transcribe.pages import (
    build_pages_rows,
    paginate_utterances,
    write_transcript_sidecar,
)

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
