"""Per-value rules for restoring the century of a 2-digit-year date.

Used by ``year_normalize``. A value ``M/D/YY`` is resolved, in order, from:

0. a manual overlay entry (``date_resolutions``) whose month, day and last
   two year digits match (``manual``); an entry that does not match is
   UNRESOLVED (``manual_mismatch``) -- nothing later overrides it;
1. the prior manifest's stored value for the same card_id group, when the
   group's non-empty stored values agree and the one value has the same
   month, day and last two year digits (``prior``); a group that has stored
   values but no such match is UNRESOLVED -- nothing later overrides it;
2. the row's own 4-digit ``display_date`` with the same month, day and
   2-digit year (``display_date``);
3. ``incident_date`` only: a 4-digit year in the row's ``title`` /
   ``asset_filename`` whose last two digits match (``title-year``);
4. ``release_date`` only: the release window -- ``20yy`` when it lies between
   the earliest 4-digit release year in the prior manifest and the new
   manifest's fetch year (``release-window``).

Several distinct candidate years from (2)/(3) are UNRESOLVED. Nothing is
ever guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["TWO_DIGIT", "Resolution", "Window", "is_four_digit", "release_window",
           "resolve_value", "two_digit_fields"]

TWO_DIGIT = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2})\s*$")
_FOUR_DIGIT_MDY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_FOUR_DIGIT_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_YEAR_IN_TEXT = re.compile(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)")


@dataclass(frozen=True)
class Window:
    """Inclusive release-year bounds; either may be unknown."""

    lower: int | None
    upper: int | None


@dataclass(frozen=True)
class Resolution:
    """A restored value and its evidence label, or a reason it stayed."""

    value: str | None = None
    evidence: str = ""
    reason: str = ""


def _mdy(value: Any) -> tuple[int, int, int] | None:
    """``(month, day, 4-digit year)`` from a 4-digit M/D/YYYY or ISO date."""
    if not isinstance(value, str):
        return None
    if m := _FOUR_DIGIT_MDY.match(value):
        return int(m[1]), int(m[2]), int(m[3])
    if m := _FOUR_DIGIT_ISO.match(value):
        return int(m[2]), int(m[3]), int(m[1])
    return None


def is_four_digit(value: Any) -> bool:
    """Whether ``value`` is a 4-digit-year M/D/YYYY or ISO date."""
    return _mdy(value) is not None


def _agrees(value: Any, month: int, day: int, yy: int) -> int | None:
    """The 4-digit year of ``value`` if it is the same date as M/D/YY."""
    parsed = _mdy(value)
    if parsed and parsed[:2] == (month, day) and parsed[2] % 100 == yy:
        return parsed[2]
    return None


def _from_prior(stored: list[str], month: int, day: int, yy: int) -> Resolution:
    distinct = list(dict.fromkeys(s.strip() for s in stored))
    if len(distinct) > 1:
        return Resolution(reason="prior_disagree")
    if _agrees(distinct[0], month, day, yy) is None:
        return Resolution(reason="prior_mismatch")
    return Resolution(distinct[0], "prior")


def _own_years(row: Mapping[str, Any], field: str, month: int, day: int,
               yy: int) -> dict[int, str]:
    """Candidate years from the row's own metadata -> evidence label."""
    years: dict[int, str] = {}
    from_display = _agrees(row.get("display_date"), month, day, yy)
    if from_display is not None:
        years[from_display] = "display_date"
    if field == "incident_date":
        for text in (row.get("title"), row.get("asset_filename")):
            for y in _YEAR_IN_TEXT.findall(text or ""):
                if int(y) % 100 == yy:
                    years.setdefault(int(y), "title-year")
    return years


def _from_window(yy: int, window: Window) -> tuple[int | None, str]:
    if window.lower is None or window.upper is None:
        return None, "no_century_evidence"
    year = 2000 + yy
    if window.lower <= year <= window.upper:
        return year, ""
    return None, "outside_release_window"


def resolve_value(value: str, row: Mapping[str, Any], field: str, stored: list[str],
                  window: Window, manual: str | None = None) -> Resolution:
    """Resolve one 2-digit-year ``value`` of ``row[field]``; ``manual`` is the
    overlay's value for this row and field, if any."""
    m = TWO_DIGIT.match(value)
    month, day, yy = int(m[1]), int(m[2]), int(m[3])
    if manual is not None:
        year = _agrees(manual, month, day, yy)
        if year is None:
            return Resolution(reason="manual_mismatch")
        return Resolution(f"{m[1]}/{m[2]}/{year}", "manual")
    if stored:
        return _from_prior(stored, month, day, yy)
    years = _own_years(row, field, month, day, yy)
    if len(years) > 1:
        return Resolution(reason="ambiguous_evidence")
    if years:
        year, label = next(iter(years.items()))
        return Resolution(f"{m[1]}/{m[2]}/{year}", label)
    if field != "release_date":
        return Resolution(reason="no_century_evidence")
    year, reason = _from_window(yy, window)
    if year is None:
        return Resolution(reason=reason)
    return Resolution(f"{m[1]}/{m[2]}/{year}", "release-window")


def release_window(prior_rows: Sequence[Mapping[str, Any]], fetch_year: int | None) -> Window:
    """Earliest 4-digit prior ``release_date`` year .. the new fetch year."""
    years = [p[2] for r in prior_rows if (p := _mdy(r.get("release_date")))]
    return Window(min(years) if years else None, fetch_year)


def two_digit_fields(prior_rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> set[str]:
    """Fields the prior holds in 2-digit form and never in 4-digit M/D/YYYY."""
    def has(field: str, pattern: re.Pattern[str]) -> bool:
        return any(pattern.match(str(r.get(field) or "")) for r in prior_rows)
    return {f for f in fields if has(f, TWO_DIGIT) and not has(f, _FOUR_DIGIT_MDY)}
