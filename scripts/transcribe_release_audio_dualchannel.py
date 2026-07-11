#!/usr/bin/env python3
"""Channel-separated re-transcription of release AUD cards via AssemblyAI.

Companion to `transcribe_release_audio.py`. The Apollo debrief tapes are true
2-channel recordings: LEFT (channel 1) carries the astronaut crew being
debriefed; RIGHT (channel 2) carries the interviewers (Dr. Berry, "Bill",
"Chuck", ...). The deployed mono transcript downmixed both channels and had to
guess speakers from timbre, producing flipping "Speaker A/B/C/D" labels that do
not map to crew-vs-interviewer.

This script keeps the channels SEPARATE (`multichannel=True`) so the channel IS
a hard crew/interviewer partition we never have to guess, and additionally runs
`speaker_labels=True` (accepted by the server together with multichannel) to get
within-channel sub-speakers (crew 1A/1B/1C, interviewers 2A/2B/...).

NON-DESTRUCTIVE: writes to an out dir the caller chooses; never touches the
deployed `ocr/<card_id>/pages.jsonl`. Outputs per card:
  <out>/<card_id>.channel.json  — raw AssemblyAI response + parsed utterances
  <out>/<card_id>.channel.txt   — merged, chronological, CREW/INTERVIEWER-tagged

Env: ASSEMBLYAI_API_KEY. Usage:
    pursue-index/.venv-audio/bin/python \
        scripts/transcribe_release_audio_dualchannel.py \
        --desktop ~/Desktop/uap_videos_071026 --out <dir> [--only <card_id>]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import assemblyai as aai

# Reuse the deployed script's JOBS map + NASA word_boost list (DRY).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe_release_audio import JOBS, NASA_TERMS  # noqa: E402

# AssemblyAI multichannel numbers channels 1..N in source order. For these
# tapes: channel 1 == LEFT == crew; channel 2 == RIGHT == interviewers.
CHANNEL_SIDE = {"1": "CREW", "2": "INTERVIEWER"}


def _side(channel) -> str:
    return CHANNEL_SIDE.get(str(channel), f"CH{channel}")


def _ts(ms: int | None) -> str:
    s = int((ms or 0) / 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


def transcribe_channels(path: Path, speaker_labels: bool = False):
    # multichannel-only is the cleaner default: it returns sentence-level
    # utterances per channel. Adding speaker_labels also yields within-channel
    # sub-speakers (crew 1A/1B/1C, interviewers 2A/2B/...) but, on these heavily
    # bleed-coupled 1971 room tapes, fragments to word level -> messy merge.
    config = aai.TranscriptionConfig(
        multichannel=True,            # keep channels separate -> hard partition
        speaker_labels=speaker_labels,
        language_code="en_us",
        word_boost=NASA_TERMS,
        boost_param="high",
        punctuate=True,
        format_text=True,
    )
    t = aai.Transcriber(config=config).transcribe(str(path))
    if t.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI failed: {t.error}")
    return t


def parse_utterances(t) -> list[dict]:
    out: list[dict] = []
    for u in (t.utterances or []):
        out.append({
            "channel": str(u.channel),
            "side": _side(u.channel),
            "speaker": str(u.speaker),
            "start": u.start,
            "end": u.end,
            "confidence": getattr(u, "confidence", None),
            "text": u.text,
        })
    out.sort(key=lambda x: (x["start"], x["channel"]))
    return out


def _norm_tokens(text: str) -> set[str]:
    return {w.strip(".,?!;:").lower() for w in text.split() if w.strip(".,?!;:")}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mark_bleed(utts: list[dict]) -> int:
    """Flag likely cross-channel bleed: near-identical text overlapping in time on
    the opposite channel. Marks the lower-confidence copy; returns flagged count."""
    n = 0
    for i, u in enumerate(utts):
        ua = _norm_tokens(u["text"])
        for v in utts[i + 1:]:
            if v["start"] > u["end"] + 800:
                break
            if v["channel"] == u["channel"]:
                continue
            overlap = min(u["end"], v["end"]) - max(u["start"], v["start"])
            if overlap <= 0:
                continue
            if _jaccard(ua, _norm_tokens(v["text"])) >= 0.6:
                lo = u if (u.get("confidence") or 0) <= (v.get("confidence") or 0) else v
                if not lo.get("bleed"):
                    lo["bleed"] = True
                    n += 1
    return n


def build_readable(utts: list[dict], label: str) -> str:
    lines = [f"# {label}", "# Channel-separated: CREW=left(ch1)  INTERVIEWER=right(ch2)",
             "# Format: [mm:ss] SIDE (sub-speaker): text   [bleed?] = likely cross-channel echo", ""]
    cur = None
    buf: list[str] = []
    head = ""
    for u in utts:
        key = (u["side"], u["speaker"])
        tag = " [bleed?]" if u.get("bleed") else ""
        piece = u["text"].strip() + tag
        if key != cur:
            if cur is not None:
                lines.append(f"{head} {' '.join(buf)}")
            cur = key
            head = f"[{_ts(u['start'])}] {u['side']} ({u['speaker']}):"
            buf = [piece]
        else:
            buf.append(piece)
    if cur is not None:
        lines.append(f"{head} {' '.join(buf)}")
    return "\n\n".join(lines) + "\n"


def process(fn: str, cid: str, label: str, desktop: Path, out: Path,
            speaker_labels: bool, suffix: str) -> None:
    p = desktop / fn
    if not p.exists():
        print(f"[aai] MISSING {p}", flush=True)
        return
    t0 = time.time()
    print(f"[aai] START {label} <- {fn}", flush=True)
    t = transcribe_channels(p, speaker_labels=speaker_labels)
    utts = parse_utterances(t)
    bleed = mark_bleed(utts)
    sides = sorted({u["side"] for u in utts})
    subs = sorted({(u["side"], u["speaker"]) for u in utts})
    per_side = {s: sum(1 for u in utts if u["side"] == s) for s in sides}
    (out / f"{cid}.channel{suffix}.txt").write_text(build_readable(utts, label))
    (out / f"{cid}.channel{suffix}.json").write_text(json.dumps({
        "card_id": cid, "label": label, "source": fn,
        "engine": "assemblyai",
        "mode": "multichannel+speaker_labels" if speaker_labels else "multichannel",
        "utterances_per_side": per_side,
        "channel_map": CHANNEL_SIDE,
        "audio_duration_s": getattr(t, "audio_duration", None),
        "sides": sides, "sub_speakers": [list(s) for s in subs],
        "bleed_flagged": bleed,
        "utterances": utts,
        "raw_response": t.json_response,
    }, indent=2))
    print(f"[aai] DONE {label}: {len(utts)} utts, per_side={per_side}, "
          f"sub_speakers={len(subs)}, bleed={bleed}, {round(time.time()-t0)}s", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desktop", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default=None, help="restrict to one card_id")
    ap.add_argument("--speaker-labels", action="store_true",
                    help="also request within-channel sub-speakers (fragments on "
                         "bleed-heavy tapes); default multichannel-only")
    ap.add_argument("--suffix", default="",
                    help="output filename suffix, e.g. '.spk'")
    args = ap.parse_args()

    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not key:
        print("ASSEMBLYAI_API_KEY not set", file=sys.stderr)
        return 2
    aai.settings.api_key = key
    args.out.mkdir(parents=True, exist_ok=True)

    for fn, cid, label in JOBS:
        if args.only and cid != args.only:
            continue
        process(fn, cid, label, args.desktop, args.out,
                args.speaker_labels, args.suffix)
    print("[aai] ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
