"""Compare war.gov ``release_date`` values by the day they name, not their spelling.

The upstream CSV switched every ``release_date`` from ``M/D/YY`` to
``M/D/YYYY`` (tranche ``92b3ec7dd872``), so an operator's ``--release-date
6/12/26`` no longer equals the manifest's ``6/12/2026``. Release dates are all
2020s publication dates, so a two-digit year reads as ``20YY``. A value that
isn't ``M/D/YY`` or ``M/D/YYYY`` is compared as an exact string, as before.
"""

from __future__ import annotations

import re
from datetime import date

_RELEASE_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*$")


def parse_release_date(value: str | None) -> date | None:
    """The day an ``M/D/YY`` or ``M/D/YYYY`` release date names, else ``None``."""
    m = _RELEASE_DATE.match(value or "")
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        return date(2000 + int(year) if len(year) == 2 else int(year), month, day)
    except ValueError:
        return None


def same_release_date(card_value: str | None, wanted: str) -> bool:
    """Whether a card's ``release_date`` names the same day as ``wanted``."""
    a, b = parse_release_date(card_value), parse_release_date(wanted)
    if a is not None and b is not None:
        return a == b
    return card_value == wanted
