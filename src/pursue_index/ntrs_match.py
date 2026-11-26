"""Title normalisation, title matching and NTRS date choice.

Pure functions over already-fetched NTRS metadata; no I/O.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from pursue_index.provenance import DateBasis

__all__ = [
    "MATCH_THRESHOLD",
    "MAX_EXTRA_CARD_TOKENS",
    "MAX_EXTRA_RESULT_TOKENS",
    "MIN_SHARED_TOKENS",
    "Copy",
    "established_date",
    "matched_copies",
    "normalize_query",
    "title_matches",
    "token_set_ratio",
]

#: Minimum token-set ratio for a result title to count as the card's title.
MATCH_THRESHOLD = 0.9

#: A match must share at least this many tokens: one shared word is a keyword.
MIN_SHARED_TOKENS = 3

#: A result may carry at most this many tokens that are not in the card title.
MAX_EXTRA_RESULT_TOKENS = 2

#: The card title may carry at most this many tokens that are not in the result.
MAX_EXTRA_CARD_TOKENS = 1

_PREFIX_RE = re.compile(r"^\s*NASA-UAP-[A-Z]*\d+[A-Z]*\s*,\s*", re.IGNORECASE)
#: Double quotes (straight, curly, low-9) and the curly single quotes, by code point.
_QUOTES = dict.fromkeys((0x22, 0x201C, 0x201D, 0x201E, 0x2018, 0x2019))
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_query(title: str) -> str:
    """The search query for a card title: no ``NASA-UAP-Dxxx,`` prefix, no quotes."""
    text = _PREFIX_RE.sub("", title).translate(_QUOTES)
    return " ".join(text.split())


def _tokens(title: str) -> set[str]:
    return set(_TOKEN_RE.findall(normalize_query(title).lower().replace("'", "")))


def token_set_ratio(a: str, b: str) -> float:
    """Token-set similarity in ``[0, 1]``: shared tokens against each side's rest.

    A title whose words are all present in the other scores 1.0, so this is a
    near-exact test only together with :data:`MIN_SHARED_TOKENS`.
    """
    ta, tb = _tokens(a), _tokens(b)
    shared = " ".join(sorted(ta & tb))
    if not shared:
        return 0.0
    left = " ".join([shared, *sorted(ta - tb)])
    right = " ".join([shared, *sorted(tb - ta)])

    def ratio(x: str, y: str) -> float:
        return difflib.SequenceMatcher(None, x, y).ratio()

    return max(ratio(shared, left), ratio(shared, right), ratio(left, right))


def title_matches(card_title: str, result_title: str) -> bool:
    """True when ``result_title`` is the card's title.

    The token-set ratio alone scores 1.0 for any subset, so the extra tokens
    on each side are capped as well.
    """
    card, result = _tokens(card_title), _tokens(result_title)
    if len(card & result) < MIN_SHARED_TOKENS:
        return False
    if len(result - card) > MAX_EXTRA_RESULT_TOKENS or len(card - result) > MAX_EXTRA_CARD_TOKENS:
        return False
    return token_set_ratio(card_title, result_title) >= MATCH_THRESHOLD


def _parse_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def established_date(result: dict[str, Any]) -> tuple[date, DateBasis] | None:
    """``distributionDate``, else ``created``; never ``publicationDate``."""
    for key, basis in (
        ("distributionDate", DateBasis.NTRS_DISTRIBUTION_DATE),
        ("created", DateBasis.NTRS_CREATED_DATE),
    ):
        day = _parse_day(result.get(key))
        if day is not None:
            return day, basis
    return None


RECORD_URL = "https://ntrs.nasa.gov/citations/{id}"
_ID_RE = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class Copy:
    ntrs_id: str
    established: date | None
    basis: DateBasis | None

    @property
    def url(self) -> str:
        return RECORD_URL.format(id=self.ntrs_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ntrs_id": self.ntrs_id,
            "record_url": self.url,
            "established_date": self.established.isoformat() if self.established else None,
            "date_basis": self.basis.value if self.basis else None,
        }


def matched_copies(card_title: str, response: dict[str, Any]) -> list[Copy]:
    results = response.get("results")
    copies: list[Copy] = []
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict) or not isinstance(result.get("title"), str):
            continue
        ntrs_id = str(result.get("id", "")).strip()
        if not _ID_RE.match(ntrs_id) or not title_matches(card_title, result["title"]):
            continue
        found = established_date(result)
        copies.append(Copy(ntrs_id, found[0] if found else None, found[1] if found else None))
    return copies
