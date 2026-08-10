"""Transcript sidecar writer — the SAME ``ocr_dir/<card_id>/{pages.jsonl,
meta.json}`` consumption path OCR'd PDFs already use.

Schema inspected before writing this module:

* ``src/pursue_index/ocr/pipeline.py`` (``_build_meta``/``ocr_card``) writes
  ``pages.jsonl`` rows shaped ``{page, text, confidence, engine}`` and a
  ``meta.json`` with ``status: "ok" | "failed"`` plus provenance fields.
* ``src/pursue_index/embed/pipeline.py::iter_card_pages`` /
  ``embed/store.py::_read_card_pages`` are the ONLY consumers: a card
  directory is picked up once ``meta.json["status"] == "ok"``, and each
  ``pages.jsonl`` row need only carry ``page``/``text`` — nothing else is
  required or interpreted.

Writing a transcript into this exact path makes an AUD card full-text
searchable/citable with ZERO changes to the embed/site consumption code —
the same trick ``scripts/integrate_transcripts.py`` already does by hand;
this module is its tested, pipeline-wired equivalent. Pagination (grouping
utterances into ~a-dozen-turn blocks) matches that script's
``paginate``/``_speaker_label`` exactly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_UTTERANCES_PER_PAGE = 12  # citation granularity: a page is ~a dozen turns


def _speaker_label(raw: str) -> str:
    return f"Speaker {raw}" if len(raw) == 1 and raw.isalpha() else raw


def paginate_utterances(
    utterances: list[dict[str, Any]], per_page: int = _UTTERANCES_PER_PAGE
) -> list[str]:
    """Group utterances into speaker-labeled text blocks, one string per page."""
    pages: list[str] = []
    for i in range(0, len(utterances), per_page):
        pages.append(_render_block(utterances[i : i + per_page]))
    return pages


def _render_block(chunk: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    cur: str | None = None
    buf: list[str] = []
    for u in chunk:
        speaker = u.get("speaker") or ""
        if speaker != cur:
            if cur is not None:
                blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
            cur = speaker
            buf = [str(u.get("text", "")).strip()]
        else:
            buf.append(str(u.get("text", "")).strip())
    if cur is not None:
        blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
    return "\n\n".join(blocks)


def build_pages_rows(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows in the exact ``pages.jsonl`` shape OCR output already uses:
    ``{page, text, confidence, engine}``."""
    return [
        {"page": n, "text": text, "confidence": 100.0, "engine": "assemblyai"}
        for n, text in enumerate(paginate_utterances(utterances), start=1)
    ]


def write_transcript_sidecar(
    card_id: str,
    out_dir: Path,
    utterances: list[dict[str, Any]],
    *,
    multichannel: bool,
    audio_duration_s: float | None,
    speakers: list[str],
    source: str,
) -> int:
    """Write ``<out_dir>/<card_id>/{pages.jsonl,meta.json}``. Returns page count."""
    card_dir = out_dir / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    rows = build_pages_rows(utterances)
    with (card_dir / "pages.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    meta = {
        "card_id": card_id,
        "engine": "assemblyai",
        "status": "ok",
        "page_count": len(rows),
        "source": source,
        "multichannel": multichannel,
        "audio_duration_s": audio_duration_s,
        "speakers": speakers,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    (card_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return len(rows)
