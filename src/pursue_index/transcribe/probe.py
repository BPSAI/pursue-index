"""Audio channel probe (ffprobe) — decides ``multichannel`` before spending.

``multichannel=True`` is only requested from AssemblyAI when the source file
is genuinely stereo (>=2 audio channels); a mono/dual-mono tape gets
``speaker_labels`` diarization instead of a channel split that would just
duplicate the same signal onto two "channels". Probing avoids guessing from
the card genre, mirroring the measured-decorrelation approach in
``scripts/transcribe_release_audio_batch2.py`` (channel COUNT here, not L/R
decorrelation — a coarser but network/binary-free-to-test signal).

``run`` is an injected seam (``subprocess.run``-shaped) so no test shells out
to a real ``ffprobe`` binary.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from pursue_index import get_logger

log = get_logger(__name__)

FFPROBE_BIN = "ffprobe"

RunFn = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)


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


def is_stereo(path: Path, *, run: RunFn = _default_run) -> bool:
    """True iff the probed channel count is >= 2. An unknown probe result
    (ffprobe failure/malformed output) is treated as mono — fail closed on
    the cheaper, safer diarization path rather than assuming a channel split."""
    channels = probe_channel_count(path, run=run)
    return channels is not None and channels >= 2
