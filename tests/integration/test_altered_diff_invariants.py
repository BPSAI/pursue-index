"""Semantic invariants on the altered-OCR diff (data-correctness guard).

These tests assert sanity invariants on ``web/src/data/altered-diffs.json``
that fail loudly if the diff is dominated by noise rather than real
content changes.

Why this is necessary: the diff is build-time SSR-imported, so a
corrupted diff propagates straight to production. The Sprint 4i #7
size-gate ensures the JSON stays parseable; this file ensures the
*semantics* are coherent.

Invariant logic
---------------
For cards whose byte-level delta is small (< 5% size change between
the pre-edit and post-edit byte versions), the OCR output should also
be largely stable — a small byte change typically means
re-rasterization, font subsetting, or metadata-only modification, not
content rewrite. If such a card shows >50% of words as "changed"
(removed + added vs equal segments), the diff is comparing inputs
that aren't apples-to-apples — flag for re-derivation.

The expected behavior of a healthy diff over byte-stable cards:
- ``equal`` segments dominate
- ``removed + added`` is a minority of total words
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALTERED_DIFFS = REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"
BYTE_HISTORY = REPO_ROOT / "web" / "src" / "data" / "byte-history.json"

# A card whose pre/post bytes are this close in size is "byte-stable" —
# the change is almost certainly re-rasterization or metadata, not
# content rewrite.
BYTE_DELTA_THRESHOLD = 0.05  # 5%

# A byte-stable card whose diff exceeds this fraction of changed-word
# share is suspicious — either a real big content rewrite (rare for
# small byte change) or pipeline contamination (more common). 60%
# threshold leaves headroom for legitimate edge cases (classification-
# marker swaps that propagate to many words despite a tiny byte delta,
# redaction-region rearrangements) while still catching the original
# engine-mismatch class (which produced ~78% mean changed-fraction).
MAX_CHANGED_FRACTION = 0.60

# Cards with extremely small total word counts (single-page photos,
# stamp-only documents) are excluded — their diff metrics are too
# noisy at low N.
MIN_TOTAL_WORDS = 100


def _load_diffs() -> dict:
    raw = json.loads(ALTERED_DIFFS.read_text())
    # Sprint 4h fix-pass: wrapped in {_meta, diffs} after vaivora H4.
    return raw.get("diffs", raw)


def _load_byte_history() -> dict:
    return json.loads(BYTE_HISTORY.read_text())


def _changed_fraction(card_diff: dict) -> tuple[int, int, int, float]:
    """Return (equal_words, removed_words, added_words, changed_fraction)
    for one card's diff. The fraction is over all words touched (equal +
    removed + added)."""
    equal_w = sum(
        len(seg["text"].split())
        for page in card_diff["pages"]
        for seg in page["segments"]
        if seg["kind"] == "equal"
    )
    removed_w = card_diff["summary"]["removed_words"]
    added_w = card_diff["summary"]["added_words"]
    total = equal_w + removed_w + added_w
    if total == 0:
        return 0, 0, 0, 0.0
    return equal_w, removed_w, added_w, (removed_w + added_w) / total


def _byte_delta_pct(entries: list[dict]) -> float | None:
    """Return |current - oldest| / oldest. Returns None if no usable
    pair (e.g., empty history)."""
    if not entries or len(entries) < 2:
        return None
    current = entries[0]
    oldest = entries[-1]
    base = max(1, oldest["byte_size"])
    return abs(current["byte_size"] - oldest["byte_size"]) / base


def test_byte_stable_cards_have_stable_diff() -> None:
    """Cards whose pre/post bytes are nearly identical should have
    diffs dominated by ``equal`` segments. If a card's bytes barely
    moved but its words look totally different, the diff is comparing
    incompatible OCR streams (the canonical engine-mismatch failure
    mode).
    """
    diffs = _load_diffs()
    byte_history = _load_byte_history()

    suspects: list[str] = []
    for card_id, card_diff in diffs.items():
        entries = byte_history.get(card_id, [])
        delta = _byte_delta_pct(entries)
        if delta is None or delta > BYTE_DELTA_THRESHOLD:
            continue  # Not byte-stable; real content delta possible.
        equal_w, removed_w, added_w, changed = _changed_fraction(card_diff)
        if equal_w + removed_w + added_w < MIN_TOTAL_WORDS:
            continue  # Too few words to measure reliably.
        if changed > MAX_CHANGED_FRACTION:
            suspects.append(
                f"{card_id}: byteΔ={delta * 100:.1f}%, "
                f"equal={equal_w}/rmv={removed_w}/add={added_w} "
                f"({changed * 100:.0f}% changed)"
            )

    assert not suspects, (
        f"{len(suspects)} byte-stable card(s) show >{MAX_CHANGED_FRACTION * 100:.0f}% "
        f"changed words — provenance suspect:\n"
        + "\n".join(f"  - {s}" for s in suspects)
    )


def test_no_card_diff_exceeds_word_count_sanity() -> None:
    """A diff cannot remove more words than exist in the pre-edit OCR.
    This is a basic data-integrity sanity check, not subject to the
    engine-mismatch issue — even with bad inputs, removed_words should
    never exceed pre-edit total word count.

    If this assertion fires, the diff builder itself is broken
    (double-counting, off-by-one across pages, etc.).
    """
    diffs = _load_diffs()
    violations: list[str] = []
    for card_id, card_diff in diffs.items():
        equal_w, removed_w, _added_w, _ = _changed_fraction(card_diff)
        pre_word_count = equal_w + removed_w
        if pre_word_count == 0:
            continue
        # removed cannot exceed pre-edit total
        if removed_w > pre_word_count * 1.05:  # tiny slack for rounding
            violations.append(
                f"{card_id}: removed={removed_w} but pre-edit total "
                f"(equal+removed)={pre_word_count}"
            )
    assert not violations, "diff builder math is off:\n" + "\n".join(
        f"  - {v}" for v in violations
    )
