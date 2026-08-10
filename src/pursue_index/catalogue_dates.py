"""Reading the dates a catalogue claim is built from (spec §6, §6d).

Two dates decide whether a catalogue row can support a prior-release claim, and
both arrive as text written by somebody else:

* **The row's own date.** It reaches the row by one of two routes, written in
  two different syntaxes: a sitemap ``<lastmod>`` element is ISO 8601
  (``2020-05-30T09:12:00Z``), an HTTP ``Last-Modified`` response header is the
  RFC 7231 date syntax (``Sat, 30 May 2020 09:12:00 GMT``). Each row states
  which basis its value rests on, and that is also the statement of how the
  value reads — so the value is parsed in the syntax its basis names, and a
  value written in some other syntax yields no date at all. A row that cannot
  be dated is a row that cannot date a claim.
* **The card's release date.** The corpus writes it as ``M/D/YY``; ISO and a
  four-digit year are read too, since the field is prose from a CSV. It is the
  publication date of the release under examination — never a document era —
  and it exists here for exactly one comparison: catalogue evidence counts as
  *prior* only when it predates it.

Both readers return ``None`` rather than a guess. Pure text and dates. No I/O.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from pursue_index.provenance import DateBasis
from pursue_index.source_index import SourceEntry

__all__ = [
    "card_release_date",
    "entry_established_date",
    "parse_http_date",
    "parse_iso_date",
]

#: Two-digit years at or below this pivot read as 20YY, the rest as 19YY — the
#: same corpus convention the era pass applies to its ``M/D/YY`` values.
_YY_PIVOT = 30

_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def parse_iso_date(value: str | None) -> date | None:
    """Read the date from an ISO 8601 sitemap ``<lastmod>``, or ``None``.

    The sitemap standard admits both a complete date (``2020-05-30``) and a
    date with a time and zone offset (``2020-05-30T09:12:00Z``), so the time
    part is optional and the calendar date is what is kept: a claim is dated to
    a day, and the offset never moves a bulk-migration timestamp by more than
    one.
    """
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_http_date(value: str | None) -> date | None:
    """Read the date from an RFC 7231 ``Last-Modified`` header, or ``None``."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def entry_established_date(entry: SourceEntry) -> date | None:
    """Read a catalogue row's date in the syntax its own basis names.

    A row whose value is absent, or is not written in the syntax its basis
    states, yields ``None`` — the row names an artifact but establishes no date
    for it, and an undated row supports no dated claim.
    """
    if entry.date_basis is DateBasis.SITEMAP_LASTMOD:
        return parse_iso_date(entry.last_modified)
    if entry.date_basis is DateBasis.HTTP_LAST_MODIFIED:
        return parse_http_date(entry.last_modified)
    return None


def card_release_date(card: dict[str, Any]) -> date | None:
    """Read a card's ``release_date`` as a calendar date, or ``None``.

    The corpus states it as ``M/D/YY`` (``5/8/26``); an ISO date and a
    four-digit ``M/D/YYYY`` are read too, because the field is CSV prose and a
    later export may write either. Anything else yields ``None``, which callers
    read as "this card supplies no date to compare against" rather than as any
    particular date.
    """
    text = str(card.get("release_date") or "").strip()
    if not text:
        return None
    iso = _ISO_DATE_RE.search(text)
    if iso:
        return _to_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    slash = _SLASH_DATE_RE.search(text)
    if not slash:
        return None
    year = int(slash.group(3))
    if len(slash.group(3)) == 2:
        year = 2000 + year if year <= _YY_PIVOT else 1900 + year
    return _to_date(year, int(slash.group(1)), int(slash.group(2)))


def _to_date(year: int, month: int, day: int) -> date | None:
    """Build a calendar date, or ``None`` when the parts name no real day."""
    try:
        return date(year, month, day)
    except ValueError:
        return None
