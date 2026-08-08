"""Row pairing for tranche diffs.

The Python twin of `web/src/components/row-pairing.ts` -- both sides
read the same case file (`tests/fixtures/row_pairing_cases.json`) so the
published /diff page and the committed tranche receipt describe a
tranche identically.

A card_id can be backed by more than one manifest row: 9 ids carry a PDF
row plus one or more VID rows, which is the upstream CSV's real shape.
Rows are never deduped, collapsed or normalized -- they are paired.

Pairing rules:

  1. Rows only ever pair inside the same card_id group.
  2. Inside a group, rows bucket by `(dvids_video_id, video_title)`.
     dvids_video_id is the upstream identifier for a video/audio row and
     distinguishes rows that are otherwise identical (the three VID rows
     under ea029a05470b8f4e share asset_url and video_title); a PDF row
     carries neither, so it buckets separately and is only ever compared
     against another PDF row.
  3. Neither keying field is one that the field diff can hide behind:
     a change to any other field -- asset_type, asset_url, title -- can
     never stop its own row from pairing, and a change to a keying field
     is caught by rule 4.
  4. If bucketing leaves exactly one row over on each side of a group,
     those two pair: a mutation of a keying field is itself a change to
     report. Two or more leftovers per side are ambiguous and stay
     unpaired rather than being matched by guesswork.
  5. Anything still unmatched is returned as an unpaired row tagged with
     its side, so a row appearing or disappearing under an existing
     card_id stays visible.

Row order within a group carries no upstream meaning, so pairing never
depends on it: reordering identical rows produces no diff.
"""

from __future__ import annotations

from typing import Any

Row = dict[str, Any]
RowPair = dict[str, Any]
UnpairedRow = dict[str, Any]

_ROW_IDENTITY_FIELDS = ("dvids_video_id", "video_title")


def row_identity_key(row: Row) -> tuple[Any, ...]:
    """Bucket key for pairing rows *within* one card_id group."""
    return tuple(row.get(f) for f in _ROW_IDENTITY_FIELDS)


def _bucket(rows: list[Row]) -> dict[tuple[Any, ...], list[Row]]:
    buckets: dict[tuple[Any, ...], list[Row]] = {}
    for row in rows:
        buckets.setdefault(row_identity_key(row), []).append(row)
    return buckets


def pair_rows_with_leftovers(
    old_rows: list[Row], new_rows: list[Row]
) -> tuple[list[tuple[Row, Row]], list[Row], list[Row]]:
    """Pair one card_id's rows. Returns `(pairs, leftover_old,
    leftover_new)` -- the leftovers are the rows with no counterpart.
    """
    old_buckets = _bucket(old_rows)
    new_buckets = _bucket(new_rows)
    pairs: list[tuple[Row, Row]] = []
    left_old: list[Row] = []
    left_new: list[Row] = []
    for key in list(old_buckets) + [k for k in new_buckets if k not in old_buckets]:
        o_rows = old_buckets.get(key, [])
        n_rows = new_buckets.get(key, [])
        n = min(len(o_rows), len(n_rows))
        pairs.extend(zip(o_rows[:n], n_rows[:n], strict=True))
        left_old.extend(o_rows[n:])
        left_new.extend(n_rows[n:])
    if len(left_old) == 1 and len(left_new) == 1:
        pairs.append((left_old[0], left_new[0]))
        return pairs, [], []
    return pairs, left_old, left_new


def pair_rows_by_identity(
    old_rows: list[Row], new_rows: list[Row]
) -> list[tuple[Row, Row]]:
    """The paired rows of one card_id group, dropping the leftovers.

    Callers that need the leftovers -- so a row added to or withdrawn
    from an existing card_id reaches the receipt -- use
    `pair_rows_with_leftovers` or `pair_rows_by_card_id` instead.
    """
    pairs, _, _ = pair_rows_with_leftovers(old_rows, new_rows)
    return pairs


def _group_by_card_id(rows: list[Row]) -> dict[str, list[Row]]:
    groups: dict[str, list[Row]] = {}
    for row in rows:
        groups.setdefault(row["card_id"], []).append(row)
    return groups


def pair_rows_by_card_id(
    prev_rows: list[Row], curr_rows: list[Row]
) -> tuple[list[RowPair], list[UnpairedRow]]:
    """Pair rows across two whole manifests, grouped by card_id.

    Returns `(pairs, unpaired)` where a pair is
    `{"card_id", "prev", "curr"}` and an unpaired row is
    `{"card_id", "side", "row"}` with side in `{"prev", "curr"}`.

    A card_id present on only one side is NOT reported here: that is an
    add/remove event, handled by the caller.
    """
    prev_groups = _group_by_card_id(prev_rows)
    curr_groups = _group_by_card_id(curr_rows)
    pairs: list[RowPair] = []
    unpaired: list[UnpairedRow] = []
    for card_id, prev_group in prev_groups.items():
        curr_group = curr_groups.get(card_id)
        if curr_group is None:
            continue
        group_pairs, left_prev, left_curr = pair_rows_with_leftovers(
            prev_group, curr_group
        )
        pairs.extend(
            {"card_id": card_id, "prev": o, "curr": n} for o, n in group_pairs
        )
        unpaired.extend(
            {"card_id": card_id, "side": "prev", "row": r} for r in left_prev
        )
        unpaired.extend(
            {"card_id": card_id, "side": "curr", "row": r} for r in left_curr
        )
    return pairs, unpaired
