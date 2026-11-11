"""Era-year resolution over the existing display-date precedence.

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
never a guess.

Two-digit ``M/D/YY`` years pivot at 30 (``≤30`` → ``20YY``, otherwise ``19YY``),
matching the clean gap in the corpus between ``/26`` (2026) and ``/45`` (1945).
That pivot is a **convention, not evidence**, and one side of it is load-bearing:
a pivoted year of 2015 or later reaches the modern-operational era, the one era
that emits a ``no_prior_release_found`` record. A 1929 document written
``5/6/29`` would arrive there on the strength of a missing century alone. So:

* :func:`parse_year` returns ``None`` for a bare pivot-derived year at or above
  :data:`~pursue_index.era_models.MODERN_MIN_YEAR` — it has no card context with
  which to corroborate one, and its contract is to refuse to guess.
* :func:`parse_year_detail` exposes the pivoted year *and* the fact that it was
  pivoted, for callers that do have that context.
* :func:`resolve_era_date` accepts such a year only when a four-digit year
  elsewhere on the same card states the same year. ``release_date`` is excluded
  from corroboration: it is the war.gov publication date (≈2026 for every card),
  so letting it corroborate would license every ``/26`` on the corpus.

An uncorroborated pivot leaves the card undated, which routes it to the explicit
triage list rather than into a bucket that asserts a negative.

The upstream CSV later began writing numeric dates as ``M/D/YYYY``. Widening the
year does not make the century evidence: the expansion is upstream's, not the
document's (one card's ``5/24/62`` became ``5/24/2962``). So on the document
date fields (:data:`SLASH_GUARDED_FIELDS`) a numeric ``M/D/YYYY`` year of 2015 or
later gets the same corroboration requirement as a pivoted ``M/D/YY`` one, and a
card that carried ``6/7/24`` resolves the same way once it carries ``6/7/2024``.
Prose and bare-year forms (``October, 2023``, ``2025``) are unchanged. A numeric
date whose four-digit year is not a ``19xx``/``20xx`` year is unparseable rather
than partially read.

Pure text; no I/O.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from pursue_index.era_models import MODERN_MIN_YEAR

__all__ = [
    "CORROBORATION_FIELDS",
    "ERA_PRECEDENCE",
    "SLASH_GUARDED_FIELDS",
    "ParsedYear",
    "ResolvedEraDate",
    "parse_year",
    "parse_year_detail",
    "resolve_era_date",
]

#: Date fields consulted for era, highest precedence first (spec §4a).
ERA_PRECEDENCE: tuple[str, ...] = ("display_date", "incident_date", "release_date")

#: Card fields whose four-digit years may corroborate a pivoted two-digit year.
#: ``release_date`` is deliberately absent — it is the war.gov publication date,
#: not evidence of when the document was authored.
CORROBORATION_FIELDS: tuple[str, ...] = ("title", "display_date", "incident_date", "description")

#: Fields on which a numeric ``M/D/YYYY`` 2015+ year needs corroboration, exactly
#: as a pivoted ``M/D/YY`` one does. ``release_date`` is excluded: it is never a
#: document era, so its year is recorded as stated.
SLASH_GUARDED_FIELDS: tuple[str, ...] = ("display_date", "incident_date")

#: Two-digit years ``<=`` this pivot are read as 20YY, the rest as 19YY.
_YY_PIVOT = 30

_FULL_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_SLASH_YY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{2})\b")
_SLASH_YYYY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(\d{4})\b")


class ParsedYear(NamedTuple):
    """A year read from a date string, and whether the century was supplied.

    ``pivot_derived`` is ``True`` when the year came from a two-digit ``M/D/YY``
    value, i.e. when the century is the pivot's convention rather than something
    the string stated. ``slash_dated`` is ``True`` when the year came from a
    numeric ``M/D/YYYY`` date (see :data:`SLASH_GUARDED_FIELDS`).
    """

    year: int | None
    pivot_derived: bool
    slash_dated: bool = False


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


def parse_year_detail(value: Any) -> ParsedYear:
    """Return the earliest defensible era year in ``value`` and its provenance.

    A full ``19xx``/``20xx`` year anywhere in the string wins (the smallest, so
    ranges resolve to their start) and is never ``pivot_derived``; it is
    ``slash_dated`` when that year is the year of a numeric ``M/D/YYYY`` date.
    Failing that, a ``M/D/YY`` two-digit year is expanded via the pivot and
    flagged as such. A numeric ``M/D/YYYY`` date whose year is not ``19xx`` or
    ``20xx`` (e.g. ``5/24/2962``) makes the whole value unparseable rather than
    being skipped over. Anything else yields ``None``.
    """
    if value is None:
        return ParsedYear(None, False)
    text = str(value)
    slash_years = [int(m) for m in _SLASH_YYYY_RE.findall(text)]
    if any(not _FULL_YEAR_RE.fullmatch(str(year)) for year in slash_years):
        return ParsedYear(None, False)
    full = [int(m) for m in _FULL_YEAR_RE.findall(text)]
    if full:
        year = min(full)
        return ParsedYear(year, False, slash_dated=year in slash_years)
    slash = _SLASH_YY_RE.search(text)
    if slash:
        return ParsedYear(_two_digit_year(int(slash.group(1))), True)
    return ParsedYear(None, False)


def parse_year(value: Any) -> int | None:
    """Return the earliest defensible era year in ``value``, or ``None``.

    A pivot-derived year at or above :data:`MODERN_MIN_YEAR` is refused here: on
    its own it is the pivot's convention rather than a stated century, and it
    would reach the one era that emits a negative. Corroborating it needs the
    rest of the card, which this function does not see — see
    :func:`resolve_era_date`. Everything else is unchanged, so a pivot-derived
    ``3/22/49`` still yields 1949.
    """
    parsed = parse_year_detail(value)
    if parsed.year is not None and parsed.pivot_derived and parsed.year >= MODERN_MIN_YEAR:
        return None
    return parsed.year


def _corroborating_years(card: dict[str, Any], exclude: str | None = None) -> set[int]:
    """Every four-digit year stated on the card, outside ``release_date``.

    ``exclude`` names the field being resolved: a value cannot corroborate
    itself, which matters once that value states a four-digit year.
    """
    years: set[int] = set()
    for field in CORROBORATION_FIELDS:
        if field == exclude:
            continue
        value = card.get(field)
        if value is None:
            continue
        years.update(int(match) for match in _FULL_YEAR_RE.findall(str(value)))
    return years


def _year_for_field(card: dict[str, Any], field: str, raw: Any) -> int | None:
    """The year ``raw`` establishes for this card, applying the century guard.

    The guard covers pivoted ``M/D/YY`` years on any field and numeric
    ``M/D/YYYY`` years on :data:`SLASH_GUARDED_FIELDS`.
    """
    parsed = parse_year_detail(raw)
    if parsed.year is None:
        return None
    guarded = parsed.pivot_derived or (parsed.slash_dated and field in SLASH_GUARDED_FIELDS)
    if not guarded or parsed.year < MODERN_MIN_YEAR:
        return parsed.year
    return parsed.year if parsed.year in _corroborating_years(card, exclude=field) else None


def resolve_era_date(card: dict[str, Any]) -> ResolvedEraDate:
    """Resolve a card's era year over :data:`ERA_PRECEDENCE`.

    The first field with a parseable era year wins; its name and raw value are
    returned alongside. A pivot-derived 2015+ year (or a numeric ``M/D/YYYY``
    2015+ year on a document date field) counts only when a four-digit year in
    another of the :data:`CORROBORATION_FIELDS` states the same year; otherwise the
    field is passed over. If no field parses, ``year``/``source_field``/``raw``
    are all ``None`` (the card is undated for era purposes, and is surfaced on
    the triage list rather than bucketed).
    """
    for field in ERA_PRECEDENCE:
        raw = card.get(field)
        year = _year_for_field(card, field, raw)
        if year is not None:
            return ResolvedEraDate(year=year, source_field=field, raw=str(raw))
    return ResolvedEraDate(year=None, source_field=None, raw=None)
