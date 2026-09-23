"""A completed AssemblyAI transcript, normalized for the sidecar writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TranscriptResult:
    """A completed transcript, normalized for the sidecar writer."""

    utterances: list[dict[str, Any]]
    audio_duration_s: float | None
    speakers: list[str]
    multichannel: bool
    raw: dict[str, Any]


def parse_utterances(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u in data.get("utterances") or []:
        out.append(
            {
                "speaker": str(u.get("speaker")) if u.get("speaker") is not None else "",
                "text": u.get("text", ""),
                "start": u.get("start") or 0.0,  # milliseconds; absent means 0
                "end": u.get("end") or 0.0,
                "channel": str(u["channel"]) if u.get("channel") is not None else None,
            }
        )
    return out


def result_from(data: dict[str, Any], *, multichannel: bool) -> TranscriptResult:
    utterances = parse_utterances(data)
    speakers = sorted({u["speaker"] for u in utterances if u["speaker"]})
    return TranscriptResult(
        utterances=utterances,
        audio_duration_s=data.get("audio_duration"),
        speakers=speakers,
        multichannel=multichannel,
        raw=data,
    )
