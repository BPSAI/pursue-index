"""Manifest-shaped helpers for the tranche receipt generator.

A manifest is a flat list of rows, not a list of cards: 9 card_ids carry
a PDF row plus one or more VID rows. Grouping (rather than keying a dict
by card_id, which keeps only the last row) is therefore the only correct
way to read one, and anything that describes a card_id to an operator
has to choose WHICH of its rows to describe it by.

Pure functions -- no filesystem, no network. `scripts/tranche_diff.py`
holds the orchestration.
"""

from __future__ import annotations

from typing import Any

from pursue_index.tranche import field_diff, row_changes

Row = dict[str, Any]


def group_by_card_id(cards: list[Row]) -> dict[str, list[Row]]:
    """Group manifest rows by card_id, preserving each id's row order."""
    groups: dict[str, list[Row]] = {}
    for c in cards:
        groups.setdefault(c["card_id"], []).append(c)
    return groups


def display_row(rows: list[Row]) -> Row:
    """The row that best describes a card_id to an operator.

    The PDF row carries the document's own title, filename and URL; a
    VID row carries the video's. When both exist under one card_id the
    PDF row is the document the card is about, so it is the one shown in
    added/removed reports and the one whose asset_url gets hashed.
    Falls back to the first row when there is no PDF row (a video-only
    or audio-only card).
    """
    for row in rows:
        if row.get("asset_type") == "PDF":
            return row
    return rows[0]


def display_rows_by_card_id(cards: list[Row]) -> dict[str, Row]:
    """`{card_id: display_row}` for every card_id in a manifest."""
    return {cid: display_row(rows) for cid, rows in group_by_card_id(cards).items()}


def build_removed_list(
    removed_ids: set[str],
    matched_old_ids: set[str],
    old_by_id: dict[str, Row],
) -> list[Row]:
    return [
        {
            "card_id": oid,
            "title": old_by_id[oid].get("title"),
            "asset_url": old_by_id[oid].get("asset_url"),
            "asset_filename": old_by_id[oid].get("asset_filename"),
        }
        for oid in sorted(removed_ids) if oid not in matched_old_ids
    ]


def build_field_only_changes(
    unchanged_ids: set[str],
    old_groups: dict[str, list[Row]],
    new_groups: dict[str, list[Row]],
) -> list[Row]:
    out: list[Row] = []
    for cid in sorted(unchanged_ids):
        diffs = field_diff(old_groups[cid], new_groups[cid])
        if diffs:
            out.append({"card_id": cid, "diffs": diffs})
    return out


def build_row_changes(
    unchanged_ids: set[str],
    old_groups: dict[str, list[Row]],
    new_groups: dict[str, list[Row]],
) -> list[Row]:
    """Rows gained or lost by card_ids present in both manifests.

    Distinct from `build_field_only_changes`: that one reports fields
    that moved on a paired row, this one reports a row that has no
    counterpart at all. Both are needed -- a card that gains a fourth
    video has no field-level diff to show.
    """
    out: list[Row] = []
    for cid in sorted(unchanged_ids):
        rows = row_changes(old_groups[cid], new_groups[cid])
        if rows:
            out.append({"card_id": cid, "rows": rows})
    return out
