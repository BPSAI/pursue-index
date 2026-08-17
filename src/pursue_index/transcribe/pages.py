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


def build_pages_rows(
    utterances: list[dict[str, Any]], start_page: int = 1
) -> list[dict[str, Any]]:
    """Rows in the exact ``pages.jsonl`` shape OCR output already uses:
    ``{page, text, confidence, engine}``.

    ``start_page`` continues an existing card's numbering, so the rows a
    second AUD row of the same card_id contributes carry page numbers of
    their own rather than repeating the first row's.
    """
    return [
        {"page": n, "text": text, "confidence": 100.0, "engine": "assemblyai"}
        for n, text in enumerate(paginate_utterances(utterances), start=start_page)
    ]


def _existing_page_count(pages_path: Path) -> int:
    """How many page rows a card directory already carries."""
    if not pages_path.exists():
        return 0
    text = pages_path.read_text(encoding="utf-8")
    return sum(1 for line in text.splitlines() if line.strip())


def _read_meta(meta_path: Path) -> dict[str, Any]:
    """The card's existing meta, or an empty dict when there is none to read."""
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _merged_rows(
    prior: list[dict[str, Any]], entry: dict[str, Any]
) -> list[dict[str, Any]]:
    """``prior`` with ``entry`` replacing the same row_key, else appended."""
    out = [r for r in prior if r.get("row_key") != entry["row_key"]]
    out.append(entry)
    return out


def write_transcript_sidecar(
    card_id: str,
    out_dir: Path,
    utterances: list[dict[str, Any]],
    *,
    row_key: str = "",
    multichannel: bool,
    audio_duration_s: float | None,
    speakers: list[str],
    source: str,
) -> int:
    """Append one row's transcript to ``<out_dir>/<card_id>/``. Returns page count.

    A card_id can be backed by more than one AUD row, and all of a card's rows
    share the one card directory the reader path consumes, so pages are
    appended and numbered continuously across rows. ``meta.json`` records a
    ``rows`` entry per transcribed row — the unit the coverage gate counts — so
    a covered row is distinguishable from an uncovered sibling.

    A row whose transcript carries no utterances contributes no pages and is
    recorded with ``pages: 0``: the call returned, but the row has no content
    and stays outstanding. ``status`` is ``ok`` only once the card carries at
    least one page, which is also the condition the reader path gates on.
    """
    card_dir = out_dir / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    pages_path = card_dir / "pages.jsonl"
    meta_path = card_dir / "meta.json"

    start_page = _existing_page_count(pages_path) + 1
    rows = build_pages_rows(utterances, start_page=start_page)
    with pages_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    prior = _read_meta(meta_path)
    entry = {
        "row_key": row_key,
        "source": source,
        "multichannel": multichannel,
        "audio_duration_s": audio_duration_s,
        "speakers": speakers,
        "pages": len(rows),
    }
    merged = _merged_rows(list(prior.get("rows", [])), entry)
    total_pages = start_page - 1 + len(rows)
    meta = {
        "card_id": card_id,
        "engine": "assemblyai",
        "status": "ok" if total_pages else "empty",
        "page_count": total_pages,
        "rows": merged,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return len(rows)
