#!/usr/bin/env python3
"""Diarized transcription of release AUD cards via AssemblyAI.

Reuses BPSAI Aurora's AssemblyAI batch-diarization approach (Mike's build on
`aurora-function-app` @ dev: `assemblyai_client.AssemblyAI_Client` +
`transcription/diarize.DiarizedSegment` / `format_diarized_segments`), adapted
for pursue: pass a LOCAL audio path straight to the SDK (no Azure SAS URL), and
add the domain tuning Aurora's meeting-audio build omits — a NASA/Apollo
`word_boost` list, `language_code`, and the high-accuracy `best` speech model —
for aged 1971-72 debriefing tapes.

Outputs per card: `<out>/<card_id>.txt` (speaker-labeled readable transcript) and
`<out>/<card_id>.json` (utterances + word-level timestamps/confidence, ms).

Env: ASSEMBLYAI_API_KEY. Usage:
    pursue-index/.venv-audio/bin/python scripts/transcribe_release_audio.py \
        --desktop ~/Desktop/uap_videos_071026 --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import assemblyai as aai

# --- Release 04 NASA Apollo AUD cards: (downloaded DOD file, card_id, label) ---
JOBS = [
    ("DOD_111830063.mp4", "ffd9dfd4bceb163f", "NASA-UAP-D026 Apollo 14 Debriefing 1971"),
    ("DOD_111830069.mp4", "69f1874d972fb44c", "NASA-UAP-D027 Apollo 14 Debriefing (Continued) 1971"),
    ("DOD_111830085.mp4", "ed534f618f0c3501", "NASA-UAP-D028 Apollo 17 Crew Medical Debriefing 1972"),
    ("DOD_111830092.mp4", "aa2e4d84861d5006", "NASA-UAP-D029 Apollo 17 Crew Medical Debriefing (Continued) 1972"),
]

# Domain terms to bias recognition (Aurora's build has none). AssemblyAI word_boost.
NASA_TERMS = [
    "Apollo", "Apollo 14", "Apollo 17", "CAPCOM", "lunar module", "command module",
    "service module", "ascent stage", "descent stage", "EVA", "extravehicular",
    "translunar injection", "cislunar", "S-IVB", "Saturn V", "PGNS", "AGS",
    "Manned Spacecraft Center", "Houston", "Mission Control", "splashdown",
    "rendezvous", "docking", "the light flash phenomena", "cosmic ray", "retina",
    "debriefing", "flight surgeon", "quarantine", "lunar surface", "regolith",
    "Fra Mauro", "Taurus-Littrow", "Cernan", "Schmitt", "Evans", "Shepard",
    "Mitchell", "Roosa",
]


@dataclass
class DiarizedSegment:  # lifted from aurora-function-app/transcription/diarize.py
    speaker: str
    text: str
    start: float
    end: float
    words: list[dict] | None = None


def _speaker_label(raw: str) -> str:
    # Aurora diarize._speaker_label: 'A' -> 'Speaker A'
    if len(raw) == 1 and raw.isalpha():
        return f"Speaker {raw}"
    return raw


def format_diarized_segments(segs: list[DiarizedSegment]) -> str:
    # Aurora diarize.format_diarized_segments: merge consecutive same-speaker turns.
    blocks: list[str] = []
    cur = None
    buf: list[str] = []
    for s in segs:
        if s.speaker != cur:
            if cur is not None:
                blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
            cur = s.speaker
            buf = [s.text.strip()]
        else:
            buf.append(s.text.strip())
    if cur is not None:
        blocks.append(f"{_speaker_label(cur)}: {' '.join(buf)}")
    return "\n\n".join(blocks)


def transcribe(path: Path) -> tuple[list[DiarizedSegment], float]:
    config = aai.TranscriptionConfig(
        speaker_labels=True,             # diarization (Aurora)
        language_code="en_us",           # default model (speech_model= is deprecated server-side)
        word_boost=NASA_TERMS,           # jargon bias (pursue addition)
        boost_param="high",
        punctuate=True,
        format_text=True,
    )
    t = aai.Transcriber(config=config).transcribe(str(path))
    if t.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI failed: {t.error}")
    segs = [
        DiarizedSegment(
            speaker=u.speaker, text=u.text, start=u.start, end=u.end,
            words=([{"text": w.text, "start": w.start, "end": w.end,
                     "confidence": w.confidence} for w in u.words]
                   if u.words else None),
        )
        for u in (t.utterances or [])
    ]
    dur = (t.audio_duration or 0) if hasattr(t, "audio_duration") else 0
    return segs, dur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desktop", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        print("ASSEMBLYAI_API_KEY not set", file=sys.stderr)
        return 2
    aai.settings.api_key = key
    args.out.mkdir(parents=True, exist_ok=True)

    for fn, cid, label in JOBS:
        p = args.desktop / fn
        if not p.exists():
            print(f"[aai] MISSING {p}", flush=True)
            continue
        t0 = time.time()
        print(f"[aai] START {label} <- {fn}", flush=True)
        segs, dur = transcribe(p)
        text = format_diarized_segments(segs)
        speakers = sorted({s.speaker for s in segs})
        (args.out / f"{cid}.txt").write_text(text)
        (args.out / f"{cid}.json").write_text(json.dumps({
            "card_id": cid, "label": label, "source": fn,
            "engine": "assemblyai", "speech_model": "default",
            "audio_duration_s": dur, "speakers": speakers,
            "utterances": [
                {"speaker": s.speaker, "text": s.text, "start": s.start,
                 "end": s.end, "words": s.words} for s in segs
            ],
        }, indent=2))
        print(f"[aai] DONE {label}: {len(segs)} utterances, {len(speakers)} speakers, "
              f"{len(text)} chars, {round(time.time()-t0)}s", flush=True)
    print("[aai] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
