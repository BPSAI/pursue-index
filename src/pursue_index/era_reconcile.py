"""One source file has one era: the dated row's era wins for every row of it.

Rows sharing a ``card_id`` name one file. Each row is resolved on its own first
(with the same two-digit-year guard as everywhere else). If the file's dated rows
agree on one era and year, each undated row takes that era and year
from the dated row, takes the date source "reconciled_from_sibling", and is labelled
with that row's key. Upstream fields are not touched. If dated rows disagree on either, nothing is
reconciled and the file has no single date: every row of it is listed with the reason,
none takes a no-prior-release negative, and the file counts once under ``undated``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, NamedTuple

from pursue_index.era_models import RECONCILED_SOURCE, CardEra, Era
from pursue_index.row_key import row_keys

__all__ = ["FileEras", "reconcile_file_eras"]


class FileEras(NamedTuple):
    """Per-row eras after reconciling, and why some undated rows were left alone."""

    cards: list[CardEra]
    conflicts: dict[str, str]  # row_key -> triage reason, for every row of a conflicting file


def _conflict_reason(dated: Sequence[CardEra]) -> str:
    found = ", ".join(f"{c.row_key}={c.era.value}/{c.year}" for c in dated)
    return f"conflicting document dates across rows of the same file: {found}"


def reconcile_file_eras(cards: Sequence[dict[str, Any]], resolved: Sequence[CardEra]) -> FileEras:
    """Key each already-classified row, then reconcile its era with its file's."""
    keys = row_keys(cards)
    keyed = [replace(c, row_key=k) for c, k in zip(resolved, keys, strict=True)]
    by_file: dict[str, list[int]] = defaultdict(list)
    for index, card in enumerate(keyed):
        if card.card_id:
            by_file[card.card_id].append(index)
    conflicts: dict[str, str] = {}
    for indexes in by_file.values():
        dated = [keyed[i] for i in indexes if keyed[i].era is not Era.UNDATED]
        undated = [i for i in indexes if keyed[i].era is Era.UNDATED]
        if len({(c.era, c.year) for c in dated}) > 1:
            reason = _conflict_reason(dated)
            conflicts.update({keyed[i].row_key: reason for i in indexes})
            continue
        if not dated or not undated:
            continue
        source = dated[0]
        for i in undated:
            keyed[i] = replace(
                keyed[i],
                era=source.era,
                year=source.year,
                date_source=RECONCILED_SOURCE,
                raw_date=source.raw_date,
                era_reconciled_from=source.row_key,
            )
    return FileEras(keyed, conflicts)
