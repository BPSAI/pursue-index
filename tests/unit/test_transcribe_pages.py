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
    repaginate_sidecar,
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


def test_paginate_utterances_by_character_budget() -> None:
    """Paginate by character budget instead of utterance count."""
    utterances = [
        {"speaker": "A", "text": "short", "start": 0, "end": 1},
        {"speaker": "A", "text": "medium text here", "start": 1, "end": 2},
        {"speaker": "A", "text": "even longer text that takes more space", "start": 2, "end": 3},
    ]
    pages = paginate_utterances(utterances, char_budget=30)
    assert len(pages) >= 2
    for page_text in pages:
        assert len(page_text) <= 30 + 100


def test_paginate_utterances_by_duration_budget() -> None:
    """Paginate by duration budget (seconds) — whichever limit hits first."""
    utterances = [
        {"speaker": "A", "text": "short", "start": 0, "end": 10},
        {"speaker": "A", "text": "medium", "start": 10, "end": 30},
        {"speaker": "A", "text": "text", "start": 30, "end": 150},
    ]
    pages = paginate_utterances(utterances, duration_budget_s=60)
    assert len(pages) >= 1


def test_paginate_utterances_never_splits_utterance() -> None:
    """A single utterance must never be split across pages."""
    utterances = [
        {"speaker": "A", "text": "short", "start": 0, "end": 1},
        {"speaker": "A", "text": "x" * 1000, "start": 1, "end": 2},
        {"speaker": "A", "text": "short", "start": 2, "end": 3},
    ]
    pages = paginate_utterances(utterances, char_budget=100)
    long_text = "x" * 1000
    for page in pages:
        if long_text in page:
            assert page.count(long_text) == 1


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
        char_budget=2500, duration_budget_s=500,
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
            "utterances": 3,
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
        char_budget=2500, duration_budget_s=500,
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


# --- repage functionality ------------------------------------------------


def test_repaginate_sidecar_rewrites_pages_with_new_pagination(tmp_path: Path) -> None:
    """Re-paginate an existing sidecar with smaller pages."""
    out_dir = tmp_path / "ocr"
    utterances = [
        {"speaker": "A", "text": "This is a longer sentence with more content " * 3 + f" - utterance {i}",
         "start": i * 10, "end": i * 10 + 9}
        for i in range(20)
    ]
    write_transcript_sidecar(
        "aud1", out_dir, utterances,
        multichannel=False, audio_duration_s=300, speakers=["A"],
        source="aud1.mp4",
        char_budget=2000,
    )
    old_meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    old_page_count = old_meta["page_count"]

    repaginate_sidecar(out_dir, "aud1", char_budget=200)

    new_meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    assert new_meta["page_count"] > old_page_count
    rows = [json.loads(line) for line in (out_dir / "aud1" / "pages.jsonl").read_text().splitlines()]
    assert all(r["page"] >= 1 for r in rows)


def test_repaginate_sidecar_is_idempotent(tmp_path: Path) -> None:
    """Running repage twice produces identical results."""
    out_dir = tmp_path / "ocr"
    utterances = [
        {"speaker": "A", "text": f"sentence {i}", "start": i * 10, "end": i * 10 + 9}
        for i in range(20)
    ]
    write_transcript_sidecar(
        "aud1", out_dir, utterances,
        multichannel=False, audio_duration_s=200, speakers=["A"],
        source="aud1.mp4",
    )

    repaginate_sidecar(out_dir, "aud1", char_budget=150)
    meta1 = json.loads((out_dir / "aud1" / "meta.json").read_text())
    rows1 = [json.loads(line) for line in (out_dir / "aud1" / "pages.jsonl").read_text().splitlines()]

    repaginate_sidecar(out_dir, "aud1", char_budget=150)
    meta2 = json.loads((out_dir / "aud1" / "meta.json").read_text())
    rows2 = [json.loads(line) for line in (out_dir / "aud1" / "pages.jsonl").read_text().splitlines()]

    assert meta1["page_count"] == meta2["page_count"]
    assert rows1 == rows2


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _numbered(n: int, start: int = 0) -> list[dict]:
    return [
        {"speaker": "A", "text": f"sentence {i}", "start": i * 10, "end": i * 10 + 9}
        for i in range(start, start + n)
    ]


def test_write_stores_utterances_once_in_a_sibling_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    write_transcript_sidecar(
        "aud1", out_dir, _numbered(5),
        multichannel=False, audio_duration_s=50, speakers=["A"], source="aud1.mp4",
    )

    meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    assert "utterances" not in meta
    assert meta["utterances_file"] == "utterances.jsonl"
    assert _read_jsonl(out_dir / "aud1" / "utterances.jsonl") == _numbered(5)


def test_second_row_appends_to_the_utterances_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    for row_key, start in (("r1", 0), ("r2", 5)):
        write_transcript_sidecar(
            "aud1", out_dir, _numbered(5, start), row_key=row_key,
            multichannel=False, audio_duration_s=50, speakers=["A"], source="aud1.mp4",
        )

    assert _read_jsonl(out_dir / "aud1" / "utterances.jsonl") == _numbered(10)


def test_repaginate_reads_utterances_from_the_sidecar_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    write_transcript_sidecar(
        "aud1", out_dir, _numbered(20),
        multichannel=False, audio_duration_s=200, speakers=["A"], source="aud1.mp4",
    )
    old_count = json.loads((out_dir / "aud1" / "meta.json").read_text())["page_count"]

    repaginate_sidecar(out_dir, "aud1", char_budget=100)

    meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    assert "utterances" not in meta
    assert meta["page_count"] > old_count
    assert len(_read_jsonl(out_dir / "aud1" / "pages.jsonl")) == meta["page_count"]


def _legacy_sidecar(out_dir: Path, utterances: list[dict]) -> Path:
    """A sidecar written before utterances moved to their own file."""
    card_dir = out_dir / "aud1"
    card_dir.mkdir(parents=True)
    (card_dir / "pages.jsonl").write_text(
        json.dumps({"page": 1, "text": "old"}) + "\n", encoding="utf-8"
    )
    (card_dir / "meta.json").write_text(
        json.dumps({
            "card_id": "aud1", "status": "ok", "page_count": 1,
            "rows": [{"row_key": "", "pages": 1}], "utterances": utterances,
        }),
        encoding="utf-8",
    )
    return card_dir


def test_repaginate_falls_back_to_inline_utterances_in_legacy_meta(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    _legacy_sidecar(out_dir, _numbered(20))

    repaginate_sidecar(out_dir, "aud1", char_budget=100)

    meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    assert meta["page_count"] > 1
    assert len(_read_jsonl(out_dir / "aud1" / "pages.jsonl")) == meta["page_count"]


def test_write_onto_legacy_sidecar_moves_inline_utterances_to_the_file(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    card_dir = _legacy_sidecar(out_dir, _numbered(3))

    write_transcript_sidecar(
        "aud1", out_dir, _numbered(2, 3), row_key="r2",
        multichannel=False, audio_duration_s=50, speakers=["A"], source="aud1.mp4",
    )

    meta = json.loads((card_dir / "meta.json").read_text())
    assert "utterances" not in meta
    assert _read_jsonl(card_dir / "utterances.jsonl") == _numbered(5)


def test_sixty_minute_fixture_produces_20_to_40_pages(tmp_path: Path) -> None:
    """60 minutes of audio with ~60k chars should paginate to 20-40 pages."""
    out_dir = tmp_path / "ocr"
    utterances = [
        {
            "speaker": "A" if i % 2 == 0 else "B",
            "text": "This is a sample utterance. " * 7,
            "start": i * 12_000,  # AssemblyAI reports milliseconds
            "end": i * 12_000 + 12_000,
        }
        for i in range(300)
    ]
    total_duration = 300 * 12
    total_chars = sum(len(u["text"]) for u in utterances)

    write_transcript_sidecar(
        "aud1", out_dir, utterances,
        multichannel=False, audio_duration_s=float(total_duration), speakers=["A", "B"],
        source="aud1.mp4",
    )

    meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    page_count = meta["page_count"]

    assert total_duration >= 3600
    assert 50000 < total_chars < 100000
    assert 20 <= page_count <= 40


def test_parse_utterances_treats_a_missing_start_or_end_as_zero() -> None:
    from pursue_index.transcribe.result import parse_utterances

    parsed = parse_utterances(
        {"utterances": [{"speaker": "A", "text": "hi"}, {"speaker": "B", "text": "yo", "start": None, "end": 900}]}
    )
    assert [(u["start"], u["end"]) for u in parsed] == [(0.0, 0.0), (0.0, 900)]


def test_paginate_tolerates_stored_utterances_with_null_times() -> None:
    utterances = [
        {"speaker": "A", "text": "one", "start": None, "end": None},
        {"speaker": "A", "text": "two", "start": 500, "end": None},
    ]
    assert len(paginate_utterances(utterances)) == 1


def test_duration_budget_is_seconds_against_millisecond_utterances() -> None:
    """Two 70 s utterances exceed a 120 s budget; two 7 s ones do not."""
    long = [{"speaker": "A", "text": "x", "start": i * 70_000, "end": (i + 1) * 70_000} for i in range(2)]
    short = [{"speaker": "A", "text": "x", "start": i * 7_000, "end": (i + 1) * 7_000} for i in range(2)]
    assert len(paginate_utterances(long, duration_budget_s=120.0)) == 2
    assert len(paginate_utterances(short, duration_budget_s=120.0)) == 1


def test_existing_five_page_sidecar_with_raw_millisecond_utterances_stays_readable(
    tmp_path: Path,
) -> None:
    """A sidecar written before the unit fix: 5 one-utterance pages, ms times."""
    card_dir = tmp_path / "ocr" / "aud1"
    card_dir.mkdir(parents=True)
    utterances = [
        {"speaker": "A", "text": f"line {i}", "start": i * 10_000, "end": i * 10_000 + 9_000}
        for i in range(5)
    ]
    (card_dir / "utterances.jsonl").write_text(
        "".join(json.dumps(u) + "\n" for u in utterances), encoding="utf-8"
    )
    (card_dir / "pages.jsonl").write_text(
        "".join(
            json.dumps({"page": i + 1, "text": f"Speaker A: line {i}", "confidence": 100.0, "engine": "assemblyai"})
            + "\n"
            for i in range(5)
        ),
        encoding="utf-8",
    )
    (card_dir / "meta.json").write_text(
        json.dumps({"card_id": "aud1", "status": "ok", "page_count": 5, "utterances_file": "utterances.jsonl"}),
        encoding="utf-8",
    )
    assert len(iter_card_pages(tmp_path / "ocr")) == 5
    repaginate_sidecar(tmp_path / "ocr", "aud1")
    meta = json.loads((card_dir / "meta.json").read_text())
    assert meta["page_count"] == 1  # 5 x 9 s fits one 120 s page
