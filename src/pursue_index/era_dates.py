"""Era-year resolution over the existing display-date precedence (PV1.3).

Era bucketing (spec §4a) needs one number per card: the year the *document*
belongs to. That year is read from the same date fields the rest of the archive
already uses, in the same order — ``display_date`` → ``incident_date`` →
``release_date`` — but with one honest restraint the era question forces:

* ``release_date`` is the war.gov **publication** date (≈2026 for every card).
  It is not evidence of when the document was authored. So while it is part of
  the precedence, a year resolved *from* ``release_date`` is not a document era;
  :func:`resolve_era_date` records the source field so the caller can refuse to
  bucket a release-only card (see :mod:`pursue_index.era_bucketing`).

Date strings in the manifest are heterogeneous — ``YYYY``, ``M/D/YY``,
``M/D/YYYY``, ``Month, YYYY``, ranges (``1948-1950``, ``August 2 - September 2,
1965``) and prose (``Late 2025``, ``1970s``). :func:`parse_year` extracts the
*earliest* four-digit era year it can defend and returns ``None`` otherwise —
never a guess. Two-digit ``M/D/YY`` years pivot at 30 (``≤30`` → ``20YY``,
otherwise ``19YY``), matching the clean gap in the corpus between ``/26`` (2026)
and ``/45`` (1945).

Pure text; no I/O.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

__all__ = [
    "ERA_PRECEDENCE",
    "ResolvedEraDate",
    "parse_year",
    "resolve_era_date",
]

#: Date fields consulted for era, highest precedence first (spec §4a / PV1.3).
ERA_PRECEDENCE: tuple[str, ...] = ("display_date", "incident_date", "release_date")

#: Two-digit years ``<=`` this pivot are read as 20YY, the rest as 19YY.
_YY_PIVOT = 30

_FULL_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_SLASH_YY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{2})\b")


class ResolvedEraDate(NamedTuple):
    """The era year for a card and where it came from.

    ``year`` is ``None`` when no field in :data:`ERA_PRECEDENCE` yields a
    defensible era year. ``source_field`` is the winning field name (or
    ``None``), and ``raw`` is that field's verbatim value — both kept so the
    assignment is auditable rather than asserted.
    """

    year: int | None
    source_field: str | None
    raw: str | None


def _two_digit_year(yy: int) -> int:
    """Expand a two-digit year via the corpus pivot (``<=30`` → 20YY)."""
    return 2000 + yy if yy <= _YY_PIVOT else 1900 + yy


def parse_year(value: Any) -> int | None:
    """Return the earliest defensible era year in ``value``, or ``None``.

    A full ``19xx``/``20xx`` year anywhere in the string wins (the smallest, so
    ranges resolve to their start). Failing that, a ``M/D/YY`` two-digit year is
    expanded via the pivot. Anything else yields ``None`` — no guessing.
    """
    if value is None:
        return None
    text = str(value)
    full = [int(m) for m in _FULL_YEAR_RE.findall(text)]
    if full:
        return min(full)
    slash = _SLASH_YY_RE.search(text)
    if slash:
        return _two_digit_year(int(slash.group(1)))
    return None


def resolve_era_date(card: dict[str, Any]) -> ResolvedEraDate:
    """Resolve a card's era year over :data:`ERA_PRECEDENCE`.

    The first field with a parseable era year wins; its name and raw value are
    returned alongside. If no field parses, ``year``/``source_field``/``raw``
    are all ``None`` (the card is undated for era purposes).
    """
    for field in ERA_PRECEDENCE:
        raw = card.get(field)
        year = parse_year(raw)
        if year is not None:
            return ResolvedEraDate(year=year, source_field=field, raw=str(raw))
    return ResolvedEraDate(year=None, source_field=None, raw=None)
