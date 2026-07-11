#!/usr/bin/env python3
"""Integrate AssemblyAI transcripts into the corpus as citable OCR-style pages.

`build_search_data` walks ``settings.ocr_dir`` for any card with a
``pages.jsonl`` (not PDF-only), so writing transcript "pages" for an AUD card
makes it full-text searchable and ``<Cite>``-able exactly like an OCR'd PDF.

Reads the transcript JSON produced by ``transcribe_release_audio.py``
(``{card_id, utterances:[{speaker,text,start,end,...}]}``) and writes, per card,
``<ocr_dir>/<card_id>/pages.jsonl`` (paginated speaker-labeled blocks, engine
``assemblyai``) + ``meta.json``. Pagination groups utterances into ~N-per-page
so citations land on a bounded chunk.

Usage: pursue-index/.venv-audio/bin/python scripts/integrate_transcripts.py \
    --transcripts <dir of *.json> --ocr-dir $PURSUE_DATA_ROOT/ocr
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

_UTTERANCES_PER_PAGE = 12  # citation-granularity: a page is ~a dozen turns


def _speaker_label(raw: str) -> str:
    return f"Speaker {raw}" if len(raw) == 1 and raw.isalpha() else raw


def paginate(utterances: list[dict], per_page: int = _UTTERANCES_PER_PAGE) -> list[str]:
    """Group utterances into pages of speaker-labeled text blocks."""
    pages: list[str] = []
    for i in range(0, len(utterances), per_page):
        chunk = utterances[i : i + per_page]
        blocks: list[str] = []
        cur = None
        buf: list[str] = []
        for u in chunk:
            sp = u["speaker"]
            if sp != cur:
                if cur is not None:
                    blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
                cur = sp
                buf = [u["text"].strip()]
            else:
                buf.append(u["text"].strip())
        if cur is not None:
            blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
        pages.append("\n\n".join(blocks))
    return pages


def integrate_one(transcript_json: Path, ocr_dir: Path) -> tuple[str, int]:
    data = json.loads(transcript_json.read_text())
    cid = data["card_id"]
    utterances = data.get("utterances") or []
    pages = paginate(utterances)
    card_dir = ocr_dir / cid
    card_dir.mkdir(parents=True, exist_ok=True)
    with (card_dir / "pages.jsonl").open("w", encoding="utf-8") as fh:
        for n, text in enumerate(pages, start=1):
            fh.write(
                json.dumps({"page": n, "text": text, "confidence": 100.0, "engine": "assemblyai"})
                + "\n"
            )
    (card_dir / "meta.json").write_text(
        json.dumps(
            {
                "card_id": cid,
                "engine": "assemblyai",
                "status": "ok",
                "page_count": len(pages),
                "source": data.get("source"),
                "audio_duration_s": data.get("audio_duration_s"),
                "speakers": data.get("speakers"),
                "finished_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )
    return cid, len(pages)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcripts", type=Path, required=True)
    ap.add_argument("--ocr-dir", type=Path, required=True)
    args = ap.parse_args()
    for tj in sorted(args.transcripts.glob("*.json")):
        cid, npages = integrate_one(tj, args.ocr_dir)
        print(f"[integrate] {cid}: {npages} page(s) -> {args.ocr_dir / cid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
