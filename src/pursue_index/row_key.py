"""The stable key of a manifest row: ``{file_key}#{n}``.

``file_key`` is the row's file identity: its ``card_id``, or, for a row with no
``card_id``, ``no-card-id-<i>``, where ``i`` is the 0-based position of the row
among the rows with no ``card_id``. Such a row is a file of its own, and no real
``card_id`` (16 hex digits) can equal that key. ``n`` is the 0-based position of
the row among the rows sharing its ``file_key``, in manifest order; a unique
``file_key`` is ``#0``. Every provenance writer takes its keys from here, so they
agree, and a key is never empty.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

__all__ = ["NO_CARD_ID_PREFIX", "file_keys", "file_part", "row_index", "row_keys"]

#: The file key of the ``i``-th row with no ``card_id`` is ``no-card-id-<i>``.
NO_CARD_ID_PREFIX = "no-card-id-"


def file_keys(cards: Sequence[dict[str, Any]]) -> list[str]:
    """The file key of every manifest row, in manifest order."""
    keys: list[str] = []
    missing = 0
    for card in cards:
        card_id = str(card.get("card_id") or "")
        if not card_id:
            card_id = f"{NO_CARD_ID_PREFIX}{missing}"
            missing += 1
        keys.append(card_id)
    return keys


def file_part(row_key: str) -> str:
    """The ``file_key`` of a ``{file_key}#{n}`` row key."""
    return row_key.rpartition("#")[0]


def row_index(row_key: str) -> int:
    """The numeric ``n`` of a ``{file_key}#{n}`` row key, so ``#2`` orders before ``#10``."""
    return int(row_key.rpartition("#")[2])


def row_keys(cards: Sequence[dict[str, Any]]) -> list[str]:
    """One key per manifest row, in manifest order."""
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for file_key in file_keys(cards):
        keys.append(f"{file_key}#{seen[file_key]}")
        seen[file_key] += 1
    return keys
