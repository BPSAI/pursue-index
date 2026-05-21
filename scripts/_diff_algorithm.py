"""Sentence-level diff algorithm extracted from build_altered_diffs.py
to keep that script under the per-file arch caps.

Pure-Python stdlib. No I/O. Deterministic. Tests live in
``tests/unit/test_build_altered_diffs.py`` against the public surface
imported by `build_altered_diffs.py`.
"""

from __future__ import annotations

import difflib
import re

_SENTENCE_SPLITTER = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\b\w+\b")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Sentence boundary = ``.``/``!``/``?``
    followed by whitespace. Collapses internal whitespace; drops empty
    segments.

    OCR-friendly: keeps the terminator with each sentence so a viewer
    can rebuild the original layout sentence-by-sentence.
    """
    if not text or not text.strip():
        return []
    parts = _SENTENCE_SPLITTER.split(text.strip())
    out = []
    for p in parts:
        normalized = re.sub(r"\s+", " ", p).strip()
        if normalized:
            out.append(normalized)
    return out


def diff_sentences(before: str, after: str) -> list[dict]:
    """Sentence-level diff. Returns a list of segments with
    ``kind ∈ {"equal", "removed", "added"}``.

    Uses ``difflib.SequenceMatcher`` against sentence-tokenized inputs.
    Replace ops are emitted as removed+added pairs so the renderer
    keeps its 3-kind surface.
    """
    pre = split_sentences(before)
    post = split_sentences(after)
    matcher = difflib.SequenceMatcher(a=pre, b=post, autojunk=False)
    segments: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segments.append({"kind": "equal", "text": " ".join(pre[i1:i2])})
        elif tag == "delete":
            segments.append({"kind": "removed", "text": " ".join(pre[i1:i2])})
        elif tag == "insert":
            segments.append({"kind": "added", "text": " ".join(post[j1:j2])})
        elif tag == "replace":
            segments.append({"kind": "removed", "text": " ".join(pre[i1:i2])})
            segments.append({"kind": "added", "text": " ".join(post[j1:j2])})
    return [s for s in segments if s["text"].strip()]


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def summarize_diff(segments: list[dict]) -> dict:
    """Aggregate (removed_words, added_words) over a flat segment list.
    Used at both page and card level."""
    removed = sum(word_count(s["text"]) for s in segments if s["kind"] == "removed")
    added = sum(word_count(s["text"]) for s in segments if s["kind"] == "added")
    return {"removed_words": removed, "added_words": added}
