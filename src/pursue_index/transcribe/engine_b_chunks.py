"""Long-form chunking for the second ASR engine: cut on pauses, stitch text.

The second engine (``engine_b_parakeet``) decodes one bounded chunk at a
time: its Transformers port has full attention only, with position
embeddings that run out at a few minutes of audio, and memory grows with
chunk length. So a recording is cut into chunks of at most
``MAX_CHUNK_S`` seconds, each cut placed at the quietest stretch in the
last ``SEARCH_S`` seconds before the limit.

A cut that lands in a real pause loses nothing, so the next chunk starts
exactly there. When the quietest stretch is not quiet (continuous speech or
crosstalk), the next chunk instead starts ``OVERLAP_S`` earlier, so a word
cut in half is heard whole by one of the two chunks. ``stitch`` then drops
the words the two chunks both produced.

Pure: frame energies in, chunk boundaries out; no audio or model here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_CHUNK_S = 60.0
SEARCH_S = 15.0
PAUSE_S = 0.4
OVERLAP_S = 2.0
#: A stretch counts as a pause when its mean energy is at most this
#: fraction of the recording's median frame energy.
PAUSE_ENERGY_RATIO = 0.3
MAX_OVERLAP_WORDS = 20


@dataclass(frozen=True)
class Chunk:
    """One decode unit: ``[start_s, end_s)``; ``overlaps_previous`` marks a
    chunk that begins inside the previous one (a cut with no pause)."""

    start_s: float
    end_s: float
    overlaps_previous: bool = False


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _quietest(energy: Sequence[float], lo: int, hi: int, width: int) -> tuple[int, float]:
    """Start frame and mean energy of the quietest ``width``-frame run in [lo, hi)."""
    width = max(1, min(width, hi - lo))
    run = sum(energy[lo:lo + width])
    best, best_at = run, lo
    for i in range(lo + 1, hi - width + 1):
        run += energy[i + width - 1] - energy[i - 1]
        if run < best:
            best, best_at = run, i
    return best_at, best / width


def plan_chunks(
    energy: Sequence[float], frame_s: float, *,
    max_chunk_s: float = MAX_CHUNK_S, search_s: float = SEARCH_S,
    pause_s: float = PAUSE_S, overlap_s: float = OVERLAP_S,
    pause_ratio: float = PAUSE_ENERGY_RATIO,
) -> list[Chunk]:
    """Chunk boundaries for a recording whose per-frame energy is ``energy``.

    ``frame_s`` is the frame hop in seconds. Every chunk is at most
    ``max_chunk_s`` long, and the chunks cover the whole recording.
    """
    if frame_s <= 0 or max_chunk_s <= search_s or overlap_s >= max_chunk_s - search_s:
        raise ValueError("need frame_s > 0 and overlap_s < max_chunk_s - search_s < max_chunk_s")
    total = len(energy)
    max_f = int(max_chunk_s / frame_s)
    search_f = int(search_s / frame_s)
    pause_f = max(1, int(pause_s / frame_s))
    overlap_f = int(overlap_s / frame_s)
    quiet = pause_ratio * _median(energy)
    chunks: list[Chunk] = []
    start, overlapped = 0, False
    while total - start > max_f:
        lo, hi = start + max_f - search_f, start + max_f
        at, level = _quietest(energy, lo, hi, pause_f)
        cut = at + pause_f // 2
        chunks.append(Chunk(start * frame_s, cut * frame_s, overlapped))
        if level <= quiet:
            start, overlapped = cut, False
        else:
            start, overlapped = cut - overlap_f, True
    if total > start or not chunks:
        chunks.append(Chunk(start * frame_s, total * frame_s, overlapped))
    return chunks


def _norm(word: str) -> str:
    return word.casefold().strip(".,?!;:\"'-—…")


def _overlap_len(prev: list[str], nxt: list[str], limit: int) -> int:
    """Longest k (>= 2) such that prev's last k words equal nxt's first k."""
    a = [_norm(w) for w in prev[-limit:]]
    b = [_norm(w) for w in nxt[:limit]]
    for k in range(min(len(a), len(b)), 1, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def stitch(texts: Sequence[str], chunks: Sequence[Chunk], max_overlap_words: int = MAX_OVERLAP_WORDS) -> str:
    """Join per-chunk texts, dropping words repeated across an overlapping cut."""
    if len(texts) != len(chunks):
        raise ValueError("one text per chunk")
    words: list[str] = []
    for text, chunk in zip(texts, chunks, strict=True):
        new = text.split()
        if chunk.overlaps_previous and words:
            new = new[_overlap_len(words, new, max_overlap_words):]
        words.extend(new)
    return " ".join(words)
