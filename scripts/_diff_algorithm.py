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

# Sprint 4k-D: when a SequenceMatcher "replace" op pairs sentences
# whose character-level similarity exceeds this ratio, collapse the
# pair to a single ``modified`` segment instead of removed+added.
# Catches in-place edits (single redaction marker inserted, typo fix,
# punctuation tweak) without losing the "this sentence changed" signal.
# Threshold tuned against the Sprint 4j corpus: 0.85 keeps real edits
# distinct while collapsing OCR-drift-style near-matches.
_MODIFIED_SIMILARITY_THRESHOLD = 0.85


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


def _emit_replace(
    pre_slice: list[str], post_slice: list[str], segments: list[dict]
) -> None:
    """Process a "replace" opcode. Pair sentences positionally and emit
    a ``modified`` segment if their char-level similarity exceeds the
    threshold; otherwise emit removed+added so the original signal
    survives.

    The pairing is positional within the slice. Longer side's leftovers
    fall back to wholesale removed/added (Sprint 4k-D — see threshold
    docstring at module top)."""
    pair_count = min(len(pre_slice), len(post_slice))
    for k in range(pair_count):
        ratio = difflib.SequenceMatcher(
            a=pre_slice[k], b=post_slice[k], autojunk=False
        ).ratio()
        if ratio >= _MODIFIED_SIMILARITY_THRESHOLD:
            segments.append({
                "kind": "modified",
                "before": pre_slice[k],
                "after": post_slice[k],
            })
        else:
            segments.append({"kind": "removed", "text": pre_slice[k]})
            segments.append({"kind": "added", "text": post_slice[k]})
    # Leftover sentences on the longer side: wholesale add/remove.
    if len(pre_slice) > pair_count:
        segments.append({
            "kind": "removed", "text": " ".join(pre_slice[pair_count:]),
        })
    if len(post_slice) > pair_count:
        segments.append({
            "kind": "added", "text": " ".join(post_slice[pair_count:]),
        })


def diff_sentences(before: str, after: str) -> list[dict]:
    """Sentence-level diff. Returns a list of segments with
    ``kind ∈ {"equal", "removed", "added", "modified"}``.

    Uses ``difflib.SequenceMatcher`` over sentence-tokenized inputs.
    Replace ops are inspected per-sentence: when paired sentences are
    >= ``_MODIFIED_SIMILARITY_THRESHOLD`` similar at the character
    level, emit a single ``modified`` segment with ``before`` /
    ``after`` keys so the renderer can show the inline edit. Below the
    threshold, emit removed+added (the legacy behavior).
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
            _emit_replace(pre[i1:i2], post[j1:j2], segments)
    return [_filter_seg(s) for s in segments if _has_content(s)]


def _has_content(seg: dict) -> bool:
    """Drop segments whose every text field is empty/whitespace."""
    if seg["kind"] == "modified":
        return bool(seg["before"].strip() or seg["after"].strip())
    return bool(seg.get("text", "").strip())


def _filter_seg(seg: dict) -> dict:
    return seg


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def summarize_diff(segments: list[dict]) -> dict:
    """Aggregate (removed_words, added_words, modified_sentences) over
    a flat segment list. Used at both page and card level.

    ``modified`` segments count as 1 sentence regardless of word delta;
    their inline before/after lets the renderer surface the edit
    without inflating the removed/added counts that the summary block
    headlines.
    """
    removed = sum(word_count(s.get("text", "")) for s in segments if s["kind"] == "removed")
    added = sum(word_count(s.get("text", "")) for s in segments if s["kind"] == "added")
    modified = sum(1 for s in segments if s["kind"] == "modified")
    return {
        "removed_words": removed,
        "added_words": added,
        "modified_sentences": modified,
    }
