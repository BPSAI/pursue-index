"""Long-form chunking and stitching for the second ASR engine (synthetic input)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from pursue_index.transcribe.engine_b_chunks import Chunk, plan_chunks, stitch

FRAME = 0.02  # 50 frames per second


def _energy(seconds: float, quiet: list[tuple[float, float]] = ()) -> list[float]:
    """Loud everywhere (1.0) except the given (start, end) quiet stretches (0.01)."""
    n = int(seconds / FRAME)
    out = [1.0] * n
    for a, b in quiet:
        for i in range(int(a / FRAME), int(b / FRAME)):
            out[i] = 0.01
    return out


def test_short_audio_is_one_chunk() -> None:
    assert plan_chunks(_energy(30), FRAME) == [Chunk(0.0, 30.0, False)]


def test_long_audio_is_cut_in_a_pause_before_the_limit() -> None:
    chunks = plan_chunks(_energy(100, quiet=[(50.0, 51.0)]), FRAME)
    assert len(chunks) == 2
    first, second = chunks
    assert 50.0 <= first.end_s <= 51.0
    assert second.start_s == first.end_s and not second.overlaps_previous
    assert second.end_s == pytest.approx(100.0)


def test_no_pause_means_a_cut_at_the_limit_with_overlap() -> None:
    chunks = plan_chunks(_energy(100), FRAME, overlap_s=2.0)
    first, second = chunks
    assert first.end_s <= 60.0
    assert second.overlaps_previous
    assert second.start_s == pytest.approx(first.end_s - 2.0)


def test_every_chunk_is_bounded_and_the_recording_is_covered() -> None:
    quiet = [(t, t + 0.6) for t in range(40, 3600, 47)]
    chunks = plan_chunks(_energy(3600, quiet=quiet), FRAME)
    assert chunks[0].start_s == 0.0 and chunks[-1].end_s == pytest.approx(3600.0)
    for a, b in pairwise(chunks):
        assert b.start_s <= a.end_s  # contiguous or overlapping, never a gap
    assert all(c.end_s - c.start_s <= 60.0 + 1e-9 for c in chunks)


def test_bad_parameters_are_refused() -> None:
    with pytest.raises(ValueError):
        plan_chunks(_energy(10), 0.0)
    with pytest.raises(ValueError):
        plan_chunks(_energy(10), FRAME, max_chunk_s=10.0, search_s=15.0)


def test_stitch_joins_pause_cut_chunks_as_is() -> None:
    chunks = [Chunk(0, 50), Chunk(50, 90)]
    assert stitch(["one two three", "four five"], chunks) == "one two three four five"


def test_stitch_drops_words_repeated_across_an_overlapping_cut() -> None:
    chunks = [Chunk(0, 60), Chunk(58, 100, overlaps_previous=True)]
    out = stitch(["we saw a bright light over the", "light over the ridge, Houston."], chunks)
    assert out == "we saw a bright light over the ridge, Houston."


def test_stitch_keeps_words_when_the_overlap_does_not_match() -> None:
    chunks = [Chunk(0, 60), Chunk(58, 100, overlaps_previous=True)]
    assert stitch(["alpha beta", "gamma delta"], chunks) == "alpha beta gamma delta"


def test_stitch_needs_one_text_per_chunk() -> None:
    with pytest.raises(ValueError):
        stitch(["a"], [Chunk(0, 1), Chunk(1, 2)])
