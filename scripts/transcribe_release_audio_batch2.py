#!/usr/bin/env python3
"""Batch-2 transcription of Release-2 NASA AUD cards via AssemblyAI.

Companion driver to ``transcribe_release_audio.py`` (mono diarization) and
``transcribe_release_audio_dualchannel.py`` (channel-separated). This batch is a
mix, decided per file by measured L/R decorrelation (ffprobe + astats on the
L-R difference signal), NOT by guessing from the card genre:

  * dual-mono / mono tapes (L==R, L-R RMS < -70 dB)  -> ``speaker_labels=True``
    diarization, speakers kept as raw AssemblyAI labels (A/B/...).
  * true-stereo tapes (L and R carry different content, L-R RMS within ~10 dB of
    the mid signal) -> ``multichannel=True``; each channel is a hard partition.
    These Release-2 stereo files are Mercury air-to-ground, NOT crew-vs-
    interviewer debriefs, so channels are labelled neutrally "Channel 1/2"
    (no CREW/INTERVIEWER semantics are asserted).

Output per card is written in the exact shape ``integrate_transcripts.py``
consumes ({card_id, utterances:[{speaker,text,start,end}], speakers, ...}), so
no intermediate re-mapping step is needed:
  <out>/<card_id>.json  — raw + parsed utterances, integrate-ready
  <out>/<card_id>.txt   — readable speaker/channel-labelled transcript

Env: ASSEMBLYAI_API_KEY. Usage:
    pursue-index/.venv-audio/bin/python \
        scripts/transcribe_release_audio_batch2.py --src <dir> --out <dir> \
        [--only <card_id>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import assemblyai as aai

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe_release_audio import (  # noqa: E402
    NASA_TERMS,
    DiarizedSegment,
    format_diarized_segments,
)

# (filename, card_id, label, mode) — mode from measured L/R decorrelation.
BATCH2_JOBS = [
    ("1007870.mp4", "9ed140b9186c20c5", "NASA-UAP-D008 Apollo 12 Medical Debriefing - Tape 12, 1969", "mono"),
    ("1007872.mp4", "002eaa383e76a277", "NASA-UAP-D009 Apollo 17 Audio Excerpt, Dec 7 1972", "mono"),
    # D010/D011 measure as waveform-decorrelated stereo, but both channels carry
    # the SAME speech program (identical words, slight offset/EQ) -> effectively a
    # mono broadcast, not two speaker groups. Mono downmix gives clean citable text.
    ("1007874.mp4", "1bc28d0e03b79e35", "NASA-UAP-D010 Mercury Atlas 9 Audio Excerpt, May 15 1963", "mono"),
    ("1007876.mp4", "ef779c3f0f7ba4d3", "NASA-UAP-D011 Mercury Atlas 9 Audio Excerpt, May 15 1963", "mono"),
    ("1007877.mp4", "35e0a7cff95a3e93", "NASA-UAP-D012 Mercury Atlas 8 Audio Excerpt, Oct 3 1962", "mono"),
    ("1007878.mp4", "01765a63bbd3f02f", "NASA-UAP-D014 Mercury-Redstone 4, July 21 1961", "mono"),
    ("1007879.mp4", "6b12c3ddc6a96008", "NASA-UAP-D013 Mercury Atlas 7, May 24 1962", "mono"),
]

# Mercury/Gemini-era jargon on top of the Apollo NASA_TERMS base (word_boost).
MERCURY_TERMS = [
    "Mercury", "Mercury-Atlas", "Mercury-Redstone", "Atlas", "Redstone",
    "Faith 7", "Sigma 7", "Aurora 7", "Friendship 7", "Liberty Bell 7",
    "Gordon Cooper", "Cooper", "Wally Schirra", "Schirra", "Scott Carpenter",
    "Carpenter", "Gus Grissom", "Grissom", "John Glenn", "Glenn",
    "capsule", "capcom", "retrofire", "retrosequence", "retropack", "retros",
    "perigee", "apogee", "reentry", "blackout", "drogue", "periscope",
    "Cape", "Canaveral", "Bermuda", "Guaymas", "Zanzibar", "Muchea",
    "Kano", "Woomera", "Hawaii", "Point Arguello", "capsule communicator",
    "go for orbit", "abort", "booster", "sustainer",
]
BATCH2_TERMS = NASA_TERMS + MERCURY_TERMS

CHANNEL_LABEL = {"1": "Channel 1", "2": "Channel 2"}


def _ts(ms: int | None) -> str:
    s = int((ms or 0) / 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def _base_config(**extra) -> aai.TranscriptionConfig:
    return aai.TranscriptionConfig(
        language_code="en_us",
        word_boost=BATCH2_TERMS,
        boost_param="high",
        punctuate=True,
        format_text=True,
        **extra,
    )


def transcribe_mono(path: Path):
    """Standard single-channel diarization (dual-mono / mono tapes)."""
    t = aai.Transcriber(config=_base_config(speaker_labels=True)).transcribe(str(path))
    if t.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI failed: {t.error}")
    segs = [
        DiarizedSegment(speaker=u.speaker, text=u.text, start=u.start, end=u.end)
        for u in (t.utterances or [])
    ]
    utts = [{"speaker": s.speaker, "text": s.text, "start": s.start, "end": s.end}
            for s in segs]
    readable = format_diarized_segments(segs)
    speakers = sorted({s.speaker for s in segs})
    return utts, readable, speakers, getattr(t, "audio_duration", None), t.json_response


def transcribe_stereo(path: Path):
    """Channel-separated (multichannel); channel == hard neutral partition."""
    t = aai.Transcriber(config=_base_config(multichannel=True)).transcribe(str(path))
    if t.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI failed: {t.error}")
    utts = []
    for u in (t.utterances or []):
        ch = str(u.channel)
        utts.append({
            "speaker": CHANNEL_LABEL.get(ch, f"Channel {ch}"),
            "text": u.text, "start": u.start, "end": u.end,
            "channel": ch,
        })
    utts.sort(key=lambda x: (x["start"], x.get("channel", "")))
    speakers = sorted({u["speaker"] for u in utts})
    readable = _readable_from_utts(utts)
    return utts, readable, speakers, getattr(t, "audio_duration", None), t.json_response


def _readable_from_utts(utts: list[dict]) -> str:
    blocks: list[str] = []
    cur = None
    head = ""
    buf: list[str] = []
    for u in utts:
        if u["speaker"] != cur:
            if cur is not None:
                blocks.append(f"{head} {' '.join(buf)}")
            cur = u["speaker"]
            head = f"[{_ts(u['start'])}] {u['speaker']}:"
            buf = [u["text"].strip()]
        else:
            buf.append(u["text"].strip())
    if cur is not None:
        blocks.append(f"{head} {' '.join(buf)}")
    return "\n\n".join(blocks) + "\n"


def process(fn: str, cid: str, label: str, mode: str, src: Path, out: Path) -> None:
    p = src / fn
    if not p.exists():
        print(f"[aai] MISSING {p}", flush=True)
        return
    t0 = time.time()
    print(f"[aai] START [{mode}] {label} <- {fn}", flush=True)
    fn_map = {"mono": transcribe_mono, "stereo": transcribe_stereo}
    utts, readable, speakers, dur, raw = fn_map[mode](p)
    (out / f"{cid}.txt").write_text(readable)
    (out / f"{cid}.json").write_text(json.dumps({
        "card_id": cid, "label": label, "source": fn,
        "engine": "assemblyai", "mode": mode,
        "audio_duration_s": dur, "speakers": speakers,
        "utterances": utts, "raw_response": raw,
    }, indent=2))
    print(f"[aai] DONE {label}: {len(utts)} utts, speakers={speakers}, "
          f"{round(time.time() - t0)}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default=None, help="restrict to one card_id")
    args = ap.parse_args()

    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        print("ASSEMBLYAI_API_KEY not set", file=sys.stderr)
        return 2
    aai.settings.api_key = key
    args.out.mkdir(parents=True, exist_ok=True)

    for fn, cid, label, mode in BATCH2_JOBS:
        if args.only and cid != args.only:
            continue
        process(fn, cid, label, mode, args.src, args.out)
    print("[aai] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
