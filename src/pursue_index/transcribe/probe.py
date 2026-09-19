"""Audio channel probe (ffprobe) — decides ``multichannel`` before spending.

``multichannel=True`` is only requested from AssemblyAI when the source file
is genuinely stereo (>=2 audio channels carrying DIFFERENT signals); a
mono/dual-mono tape gets ``speaker_labels`` diarization instead of a channel
split that would just duplicate the same signal onto two "channels" and return
every word once per channel. Probing avoids guessing from the card genre.

Two steps: ``ffprobe`` gives the channel count, then, for >=2 channels,
``ffmpeg`` measures the RMS level of the difference channel (``c0 - c1``) via
``astats``. Identical channels cancel to silence, so a difference RMS below
``DUAL_MONO_RMS_DB`` is dual-mono. Nothing is decoded into Python.

``run`` is an injected seam (``subprocess.run``-shaped) so no test shells out
to a real ``ffprobe``/``ffmpeg`` binary.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from pursue_index import get_logger

log = get_logger(__name__)

FFPROBE_BIN = "ffprobe"
FFMPEG_BIN = "ffmpeg"

# Difference-channel (L - R) RMS level below which two channels count as one
# signal. Identical channels cancel to -inf dB; -60 dB leaves room for
# codec noise on a dual-mono file while staying far under any real stereo image.
DUAL_MONO_RMS_DB = -60.0

_PROBE_TIMEOUT_S = 30
# Decoding the whole file to measure the difference channel scales with its
# length, so it gets a far larger bound than a header probe.
_DECODE_TIMEOUT_S = 900

RunFn = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

_RMS_LEVEL_RE = re.compile(r"RMS level dB:\s*(-?inf|-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _default_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    timeout = _DECODE_TIMEOUT_S if cmd[0] == FFMPEG_BIN else _PROBE_TIMEOUT_S
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe_channel_count(path: Path, *, run: RunFn = _default_run) -> int | None:
    """Channel count of ``path``'s first audio stream, or ``None`` if
    ffprobe fails, returns malformed output, or finds no audio stream."""
    cmd = [
        FFPROBE_BIN, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=channels", "-of", "json", str(path),
    ]
    result = run(cmd)
    if result.returncode != 0:
        log.warning(
            "transcribe.probe.ffprobe_failed", path=str(path), stderr=result.stderr
        )
        return None
    try:
        data = json.loads(result.stdout)
        return int(data["streams"][0]["channels"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError):
        log.warning("transcribe.probe.unparseable", path=str(path))
        return None


def difference_rms_db(path: Path, *, run: RunFn = _default_run) -> float | None:
    """RMS level (dB) of the first two channels' difference, or ``None`` if
    ffmpeg fails or its ``astats`` summary can't be read.

    ``-inf`` means the channels cancel exactly (dual-mono). ``astats`` prints a
    per-channel block and then ``Overall``; with the single mixed-down
    difference channel the last ``RMS level dB`` line is the overall figure.
    """
    cmd = [
        FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path),
        "-af", "pan=mono|c0=c0-c1,astats=metadata=1:reset=0", "-f", "null", "-",
    ]
    try:
        result = run(cmd)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning(
            "transcribe.probe.ffmpeg_failed", path=str(path), error=type(exc).__name__
        )
        return None
    if result.returncode != 0:
        log.warning(
            "transcribe.probe.ffmpeg_failed", path=str(path), stderr=result.stderr
        )
        return None
    matches = _RMS_LEVEL_RE.findall(result.stderr)
    if not matches:
        log.warning("transcribe.probe.ffmpeg_unparseable", path=str(path))
        return None
    return float(matches[-1])


def is_stereo(path: Path, *, run: RunFn = _default_run) -> bool:
    """True iff the file has >=2 channels that carry different signals.

    Dual-mono (two channels, one signal) is NOT stereo: requesting
    ``multichannel`` for it returns every word once per channel. An unknown
    channel count (ffprobe failure/malformed output) is treated as mono — fail
    closed on the cheaper diarization path. If only the difference check fails
    (ffmpeg error/timeout), the channel-count answer stands and the reason is
    logged; the CLI's coverage gate is downstream.
    """
    channels = probe_channel_count(path, run=run)
    if channels is None or channels < 2:
        return False
    diff_db = difference_rms_db(path, run=run)
    if diff_db is None:
        log.warning(
            "transcribe.probe.dual_mono_check_skipped", path=str(path), channels=channels
        )
        return True
    if diff_db < DUAL_MONO_RMS_DB:
        log.info(
            "transcribe.probe.dual_mono", path=str(path), difference_rms_db=diff_db
        )
        return False
    return True
