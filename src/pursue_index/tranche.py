"""Pure-logic helpers for tranche diff classification.

The tranche-diff analyzer (`scripts/tranche_diff.py`) classifies every
new card_id in an incoming manifest as one of three classes:

  - Class A (confirmed rename) — bytes match an existing registry entry
  - Class B (net-new content) — new bytes AND no title-continuity match
  - Class C (suspicious replacement) — new bytes BUT title-continuity
    heuristics match an existing card. Quarantined for manual review.

This module owns the pure-logic parts of that decision (heuristics,
Levenshtein, numeric-id extraction) so they can be tested without any
network, filesystem, or boto3 dependency.

The orchestration (loading manifests + registry, fetching bytes, writing
reports) lives in `scripts/tranche_diff.py`.
"""

from __future__ import annotations

import re
from typing import Any

from pursue_index.tranche_rows import (
    pair_rows_by_card_id,
    pair_rows_by_identity,
    pair_rows_with_leftovers,
)

__all__ = [
    "DIFF_SKIP_FIELDS",
    "LOCAL_CURATION_FIELDS",
    "build_byte_sha_index",
    "extract_numeric_id",
    "field_diff",
    "find_title_continuity",
    "levenshtein",
    "pair_rows_by_card_id",
    "pair_rows_by_identity",
    "pair_rows_with_leftovers",
    "row_changes",
]

_NUMERIC_ID_RE = re.compile(r"-(?:D|VM|PR|VID)0*(\d+)\b")
_FILENAME_LEVENSHTEIN_THRESHOLD = 8
_N_A_VALUES = {"", "N/A", "n/a", None}

# Fields `field_diff` never reports. `card_id` is the pairing key, not a
# mutable field; `raw` carries upstream CSV metadata that is allowed to
# wobble. The /diff page keeps an identical set (`DIFF_SKIP_FIELDS` in
# web/src/components/diff-helpers.ts) and a test pins the two equal, so
# the published page and the committed receipt exclude the same fields.
DIFF_SKIP_FIELDS = {"card_id", "raw"}

# Fields written by OUR curation pipeline rather than by war.gov. Kept
# separate from `DIFF_SKIP_FIELDS` because the reason differs: those are
# the pairing key and volatile upstream metadata, these are this
# project's own editorial work. A tranche receipt describes what the
# agency changed, so a curator approving a display date must not appear
# in it as an upstream edit. The /diff page holds the identical set
# (`LOCAL_CURATION_FIELDS`), pinned equal by the same test.
LOCAL_CURATION_FIELDS = {
    "display_date",
    "display_date_range",
    "display_date_abstention",
    "display_date_approved_at",
    "display_date_curator",
    "display_date_evidence",
    "display_date_evidence_card_ref",
    "manifest_incident_date_raw",
}

# Boolean fields are compared by truthiness so a snapshot predating the
# field (value absent -> None) reads equal to an explicit False. Without
# this, adding `featured` flags every non-featured card as "changed" the
# first time a post-column snapshot is diffed against a pre-column one.
# Ported from the /diff page's `_BOOLEAN_FIELDS`, which carried the rule
# from the start; the receipt did not, and reported 210 introductions on
# 6be2c64e->5216a20b that the page correctly reported as none.
_BOOLEAN_FIELDS = {"redacted", "featured"}


def levenshtein(a: str, b: str) -> int:
    """Plain dynamic-programming Levenshtein distance.

    Adequate for our scale (per-tranche: ~133 changed cards × ~150 prior
    cards × ~100 chars/filename ≈ 2M cell ops, all-in well under a
    second). No external dep needed; the corpus does not justify pulling
    in rapidfuzz for one heuristic check.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Two-row optimization — O(min(|a|, |b|)) memory.
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        curr = [i] + [0] * len(a)
        for j, ca in enumerate(a, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,        # insert
                prev[j] + 1,            # delete
                prev[j - 1] + cost,     # substitute
            )
        prev = curr
    return prev[-1]


def extract_numeric_id(title: str | None) -> int | None:
    """Pull the numeric identifier from a `(DOW|NASA|FBI)-UAP-(D|VM|PR|VID)\\d+`
    title pattern. Strips zero-padding so `D33` and `D033` map to the same int.
    Returns None on no match.
    """
    if not title:
        return None
    m = _NUMERIC_ID_RE.search(title)
    return int(m.group(1)) if m else None


def _is_meaningful(value: Any) -> bool:
    """Filter out N/A-equivalent sentinels from heuristic comparison.

    A field with value 'N/A' or empty string is too unspecific to base a
    rename hypothesis on — both old and new cards can carry 'N/A' for
    incident_date without being the same document. Treat such values as
    non-comparable for continuity purposes.
    """
    return value not in _N_A_VALUES


def find_title_continuity(
    new_card: dict[str, Any],
    candidate_old_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of `{card_id, card, reasons[]}` for each candidate
    old card that triggers any of the four continuity heuristics:

      1. Same agency + same incident_date (both meaningful)
      2. Same incident_location (meaningful)
      3. Matching numeric ID extracted from title
      4. asset_filename Levenshtein distance ≤ 8

    Bias is to over-flag (Class C false-positive = operator review;
    Class C false-negative = silent acceptance of possible tampering).
    Returns empty list if no candidate matches.
    """
    new_agency = new_card.get("agency")
    new_date = new_card.get("incident_date")
    new_loc = new_card.get("incident_location")
    new_filename = new_card.get("asset_filename") or ""
    new_num = extract_numeric_id(new_card.get("title", ""))

    matches: list[dict[str, Any]] = []
    for old in candidate_old_cards:
        reasons = _continuity_reasons(
            old, new_agency, new_date, new_loc, new_filename, new_num
        )
        if reasons:
            matches.append({
                "card_id": old.get("card_id"),
                "card": old,
                "reasons": reasons,
            })
    return matches


def _continuity_reasons(
    old: dict[str, Any],
    new_agency: Any,
    new_date: Any,
    new_loc: Any,
    new_filename: str,
    new_num: int | None,
) -> list[str]:
    reasons: list[str] = []
    old_date = old.get("incident_date")
    if (_is_meaningful(new_agency) and old.get("agency") == new_agency
            and _is_meaningful(new_date) and old_date == new_date):
        reasons.append(f"same agency + same incident_date ({new_date})")
    old_loc = old.get("incident_location")
    if (_is_meaningful(new_loc) and old_loc == new_loc):
        reasons.append(f"same incident_location ({new_loc})")
    old_num = extract_numeric_id(old.get("title", ""))
    if new_num is not None and new_num == old_num:
        reasons.append(f"matching numeric id {new_num}")
    old_filename = old.get("asset_filename") or ""
    if new_filename and old_filename:
        dist = levenshtein(new_filename, old_filename)
        if dist <= _FILENAME_LEVENSHTEIN_THRESHOLD:
            reasons.append(f"filename Levenshtein distance {dist}")
    return reasons


def build_byte_sha_index(
    registry: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    """Invert the registry to `{byte_sha256: [card_id, card_id, ...]}`.

    Used by the diff classifier to spot byte-sha collisions across the
    old → new boundary (Class A detection). Multiple old card_ids
    sharing one byte_sha is itself a meaningful signal — preserved.
    """
    out: dict[str, list[str]] = {}
    for card_id, rows in registry.items():
        for row in rows:
            sha = row.get("byte_sha256")
            if not sha:
                continue
            out.setdefault(sha, []).append(card_id)
    # Dedupe preserving order — a card_id with multiple registry rows
    # under the same byte_sha (rare) only needs to appear once per sha.
    return {sha: list(dict.fromkeys(ids)) for sha, ids in out.items()}


def field_diff(
    old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Field-by-field diff across every row pair sharing one card_id.

    `old_rows`/`new_rows` are ALL the manifest rows for a single card_id
    on each side (a card_id backed by only one row per side is simply a
    one-element list). Rows are paired by `pair_rows_by_identity`
    (PDF-to-PDF, VID-to-VID -- never collapsed to "last row wins" before
    diffing, which would compare mismatched rows). Each pair is diffed
    independently and the changed fields are unioned across pairs -- a
    field that changed on ANY paired row is reported once, keeping the
    first pair's old/new values.

    Rows left unpaired (added to or withdrawn from the card_id) carry no
    field-level diff; `row_changes` reports them.

    Skips `DIFF_SKIP_FIELDS` (the pairing key and volatile upstream
    metadata) and `LOCAL_CURATION_FIELDS` (this project's own editorial
    writes, which are not upstream edits). Returns a list of
    `{field, old, new}` dicts, sorted by field name.
    """
    skip = DIFF_SKIP_FIELDS | LOCAL_CURATION_FIELDS
    changed: dict[str, dict[str, Any]] = {}
    for old, new in pair_rows_by_identity(old_rows, new_rows):
        for k in set(old) | set(new):
            if k in skip or k in changed:
                continue
            ov, nv = old.get(k), new.get(k)
            if _values_differ(k, ov, nv):
                changed[k] = {"field": k, "old": ov, "new": nv}
    return [changed[k] for k in sorted(changed)]


def _values_differ(field: str, old_value: Any, new_value: Any) -> bool:
    """Whether two paired-row values count as a reportable change.

    Booleans compare by truthiness (see `_BOOLEAN_FIELDS`); everything
    else compares exactly, so an empty string becoming None stays a
    reportable deletion. `field_diff`'s callers read both sides with
    `dict.get()`, which already makes an absent key equal to an explicit
    None — the /diff page reproduces that with a `?? null` normalization.
    """
    if field in _BOOLEAN_FIELDS:
        return bool(old_value) != bool(new_value)
    return old_value != new_value


def row_changes(
    old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rows one card_id gained or lost between two manifests.

    Returns `{"side", "asset_type", "title", "asset_url",
    "dvids_video_id"}` entries, `side` being "removed" for a row present
    only in `old_rows` and "added" for one present only in `new_rows`.
    A card_id whose row set is unchanged returns an empty list.
    """
    _, left_old, left_new = pair_rows_with_leftovers(old_rows, new_rows)
    return [
        {
            "side": side,
            "asset_type": row.get("asset_type"),
            "title": row.get("title"),
            "asset_url": row.get("asset_url"),
            "dvids_video_id": row.get("dvids_video_id"),
        }
        for side, rows in (("removed", left_old), ("added", left_new))
        for row in rows
    ]
