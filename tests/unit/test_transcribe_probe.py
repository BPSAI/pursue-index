"""Audio channel probe — ffprobe, fully injectable so tests never shell out.

``multichannel=True`` is only requested from AssemblyAI when the source file
is true stereo (>=2 channels carrying different signals); mono and dual-mono
tapes (two channels, one signal) get diarization instead of a channel split.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pursue_index.transcribe.probe import (
    DUAL_MONO_RMS_DB,
    is_stereo,
    probe_channel_count,
)


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


def _astats_stderr(rms_db: str) -> str:
    """ffmpeg's ``astats`` log summary for the ``c0-c1`` difference channel."""
    return (
        "[Parsed_astats_1 @ 0x1] Channel: 1\n"
        f"[Parsed_astats_1 @ 0x1] RMS level dB: {rms_db}\n"
        "[Parsed_astats_1 @ 0x1] Overall\n"
        "[Parsed_astats_1 @ 0x1] RMS difference: 1.0\n"
        f"[Parsed_astats_1 @ 0x1] RMS level dB: {rms_db}\n"
        "[Parsed_astats_1 @ 0x1] Peak level dB: -3.0\n"
    )


def _probe_and_ffmpeg_run(
    channels: int,
    *,
    diff_rms_db: str | None = None,
    ffmpeg_returncode: int = 0,
    ffmpeg_stderr: str | None = None,
    calls: list[list[str]] | None = None,
):
    """Route ffprobe (channel count) and ffmpeg (difference RMS) to canned output."""

    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if calls is not None:
            calls.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f'{{"streams": [{{"channels": {channels}}}]}}', stderr=""
            )
        stderr = ffmpeg_stderr
        if stderr is None:
            stderr = _astats_stderr(diff_rms_db or "-inf")
        return subprocess.CompletedProcess(cmd, ffmpeg_returncode, stdout="", stderr=stderr)

    return run


def test_is_stereo_true_for_genuinely_different_channels() -> None:
    run = _probe_and_ffmpeg_run(2, diff_rms_db="-18.06")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_false_for_mono() -> None:
    calls: list[list[str]] = []
    run = _probe_and_ffmpeg_run(1, calls=calls)
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False
    # A single channel is never worth decoding for a difference check.
    assert [c[0] for c in calls] == ["ffprobe"]


def test_is_stereo_false_for_dual_mono_silent_difference() -> None:
    """Two channels carrying the same signal: L-R is digital silence (-inf dB)."""
    run = _probe_and_ffmpeg_run(2, diff_rms_db="-inf")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False


def test_is_stereo_false_for_near_identical_channels_below_threshold() -> None:
    run = _probe_and_ffmpeg_run(2, diff_rms_db="-90.3")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False


def test_is_stereo_true_just_above_dual_mono_threshold() -> None:
    run = _probe_and_ffmpeg_run(2, diff_rms_db=str(DUAL_MONO_RMS_DB + 1))
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_difference_check_uses_ffmpeg_pan_and_astats() -> None:
    calls: list[list[str]] = []
    run = _probe_and_ffmpeg_run(2, diff_rms_db="-20", calls=calls)
    is_stereo(Path("/tmp/a.mp4"), run=run)
    ffmpeg_cmd = next(c for c in calls if c[0] == "ffmpeg")
    joined = " ".join(ffmpeg_cmd)
    assert "pan=mono|c0=c0-c1" in joined
    assert "astats" in joined
    assert "/tmp/a.mp4" in ffmpeg_cmd


def test_is_stereo_falls_back_to_channel_count_when_ffmpeg_fails() -> None:
    """ffmpeg failure is not fail-closed here: the channel-count answer stands
    (the CLI's coverage gate is downstream)."""
    run = _probe_and_ffmpeg_run(2, ffmpeg_returncode=1, ffmpeg_stderr="Invalid data")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_falls_back_when_ffmpeg_output_has_no_rms_line() -> None:
    run = _probe_and_ffmpeg_run(2, ffmpeg_stderr="nothing useful here\n")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_falls_back_when_ffmpeg_times_out() -> None:
    def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                cmd, 0, stdout='{"streams": [{"channels": 2}]}', stderr=""
            )
        raise subprocess.TimeoutExpired(cmd, 1)

    assert is_stereo(Path("/tmp/a.mp4"), run=run) is True


def test_is_stereo_false_when_probe_fails_unknown_treated_as_mono() -> None:
    run = _fake_run(1, stderr="boom")
    assert is_stereo(Path("/tmp/a.mp4"), run=run) is False
