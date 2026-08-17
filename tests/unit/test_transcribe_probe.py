"""Audio channel probe — ffprobe, fully injectable so tests never shell out.

``multichannel=True`` is only requested from AssemblyAI when the source file
is true stereo (>=2 channels); mono/dual-mono tapes get diarization instead
of a channel split.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pursue_index.transcribe.probe import is_stereo, probe_channel_count


def _fake_run(returncode: int, stdout: str = "", stderr: str = ""):
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return run


def test_probe_channel_count_parses_stereo() -> None:
    run = _fake_run(0, stdout='{"streams": [{"channels": 2}]}')
    assert probe_channel_count(Path("/tmp/a.mp4"), run=run) == 2


def test_probe_channel_count_parses_mono() -> None:
    run = _fake_run(0, stdout='{"streams": [{"channels": 1}]}')
    assert probe_channel_count(Path("/tmp/a.mp4"), run=run) == 1


def test_probe_channel_count_none_on_ffprobe_failure() -> None:
    run = _fake_run(1, stderr="no such file")
    assert probe_channel_count(Path("/tmp/missing.mp4"), run=run) is None


def test_probe_channel_count_none_on_malformed_json() -> None:
    run = _fake_run(0, stdout="not json")
    assert probe_channel_count(Path("/tmp/a.mp4"), run=run) is None


def test_probe_channel_count_none_on_no_audio_stream() -> None:
    run = _fake_run(0, stdout='{"streams": []}')
    assert probe_channel_count(Path("/tmp/a.mp4"), run=run) is None


def test_is_stereo_true_for_two_channels() -> None:
    run = _fake_run(0, stdout='{"streams": [{"channels": 2}]}')
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_false_for_mono() -> None:
    run = _fake_run(0, stdout='{"streams": [{"channels": 1}]}')
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False


def test_is_stereo_false_when_probe_fails_unknown_treated_as_mono() -> None:
    run = _fake_run(1, stderr="boom")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False
