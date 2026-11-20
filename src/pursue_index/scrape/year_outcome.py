"""Bookkeeping for one normalization run: the ``DateReport`` and how each
resolved or UNRESOLVED value is recorded in it (``year_normalize``).

An UNRESOLVED value is either a new flag (``unresolved``) or, when the
prior's marker for the same card_id and field holds the same upstream value,
a carried open item (``open``) that keeps the marker's ``first_flagged_*``
(``year_marker``).

What an UNRESOLVED field is written as: the 4-digit value the paired prior
row stores for it, unchanged (``prior_mismatch`` / ``prior_disagree`` --
each row keeps its own), so good published data is never emptied or
overwritten and no field change is reported; EMPTY when the paired prior
row stores no 4-digit value. Rows are paired with the prior exactly as the
field diff pairs them (``tranche_rows.pair_rows_by_identity``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pursue_index.scrape.date_resolutions import Overlay
from pursue_index.scrape.year_marker import carries, new_marker, open_entry
from pursue_index.scrape.year_resolve import Resolution, Window, is_four_digit
from pursue_index.tranche_rows import pair_rows_by_identity

__all__ = ["DateReport", "RunContext", "kept_value", "paired_priors", "record_resolved",
           "record_unresolved"]


@dataclass
class DateReport:
    """What the normalization did, for the receipt and the summaries.

    ``unresolved`` are new flags; ``open`` are items a prior marker already
    carries (same upstream value), still unresolved but not counted as new.
    ``manual_rows`` are rows a manual overlay entry resolved where the prior
    did not already store that value. ``considered`` is True when any new
    row carried a 2-digit-year value. ``window`` is the release window, set
    only when a row reached that rule.
    """

    unresolved: list[dict[str, Any]] = field(default_factory=list)
    open: list[dict[str, Any]] = field(default_factory=list)
    window_rows: list[dict[str, Any]] = field(default_factory=list)
    manual_rows: list[dict[str, Any]] = field(default_factory=list)
    window: Window | None = None
    passed_through: int = 0
    considered: bool = False


@dataclass(frozen=True)
class RunContext:
    """What every row of one run is resolved against."""

    stored: Mapping[tuple[Any, str], list[str]]
    window: Window
    markers: Mapping[tuple[Any, str], dict[str, Any]]
    overlay: Overlay
    tranche: str | None
    fetched_at: str | None


def _entry(row: Mapping[str, Any], fld: str, raw: str) -> dict[str, Any]:
    return {"card_id": row.get("card_id"), "title": row.get("title"), "field": fld, "raw": raw}


def paired_priors(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]]
                  ) -> list[Mapping[str, Any] | None]:
    """The prior row each of ``rows`` pairs with (or None), by position."""
    groups: dict[Any, tuple[list, list]] = {}
    for row in rows:
        groups.setdefault(row.get("card_id"), ([], []))[0].append(row)
    for row in prior_rows:
        if row.get("card_id") in groups:
            groups[row.get("card_id")][1].append(row)
    paired: dict[int, Mapping[str, Any]] = {}
    for new_rows, old_rows in groups.values():
        for old, new in pair_rows_by_identity(old_rows, new_rows):
            paired[id(new)] = old
    return [paired.get(id(row)) for row in rows]


def kept_value(paired: Mapping[str, Any] | None, fld: str) -> str | None:
    """An UNRESOLVED field's value: the paired prior's 4-digit value, else empty."""
    value = (paired or {}).get(fld)
    return value if is_four_digit(value) else None


def record_unresolved(row: Mapping[str, Any], fld: str, raw: str, reason: str,
                      ctx: RunContext, report: DateReport) -> dict[str, Any]:
    """Report one UNRESOLVED value (new flag or carried item); its marker."""
    prior = ctx.markers.get((row.get("card_id"), fld))
    if carries(prior, raw):
        marker = {**prior, "reason": reason}
        report.open.append(open_entry(_entry(row, fld, raw), marker))
        return marker
    report.unresolved.append({**_entry(row, fld, raw), "reason": reason})
    return new_marker(fld, raw, reason, ctx.tranche, ctx.fetched_at)


def record_resolved(row: Mapping[str, Any], fld: str, raw: str, res: Resolution, stored: list[str],
              ctx: RunContext, report: DateReport) -> None:
    """Report a resolved value when its evidence is reported (window, manual)."""
    if res.evidence == "release-window":
        report.window_rows.append({**_entry(row, fld, raw), "value": res.value,
                                   "evidence": res.evidence})
    if res.evidence == "manual" and {s.strip() for s in stored} != {res.value}:
        entry = ctx.overlay[(row.get("card_id"), fld)]
        report.manual_rows.append({**_entry(row, fld, raw), "value": res.value,
                                   "evidence": res.evidence, "curator": entry.get("curator"),
                                   "approved_at": entry.get("approved_at")})
