"""Card identifier extraction with the false-NAID guard (spec §6).

Cards carry identifiers that *can* be resolved against public archives — FBI
file and serial numbers, CIA CREST ``CIA-RDP…`` document IDs, Project Blue Book
case numbers, and genuine NARA National Archives Identifiers (NAIDs). This
module extracts them, and its whole reason for existing is one refusal:

**A record-group finding-aid number is never a NAID.** Many card titles begin
``<record-group>_<box/folder>_…`` — ``255_413270_…``, ``331_120752_…``,
``341_110448_…``. The leading number is a NARA *record group* (255 = NASA,
331 = Allied WWII HQ, 341 = HQ USAF) and the second is a box/folder finding-aid
location. Neither is a NAID. Resolved as a NAID against NARA's catalog,
``413270`` returns "Travel to the U.S. - GARIOA Students" — an entirely
unrelated record. Auto-linking it would emit a *false citation on a citable
archive*, which is worse than emitting none. So NAID extraction is deliberately
conservative: it only accepts a number that appears in an explicit NAID context
(the word ``NAID`` / "National Archives Identifier" / a ``catalog.archives.gov``
URL), **and** never a number that also appears as a record-group finding-aid
location in the same text.

Pure text. No I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "Identifier",
    "IdentifierKind",
    "extract_blue_book",
    "extract_crest",
    "extract_fbi_files",
    "extract_identifiers",
    "extract_naids",
    "is_rg_finding_aid_token",
    "rg_finding_aid_numbers",
]


class IdentifierKind(StrEnum):
    """The identifier families the resolver knows how to resolve."""

    FBI_FILE = "fbi_file"
    CIA_CREST = "cia_crest"
    BLUE_BOOK_CASE = "blue_book_case"
    NAID = "naid"


@dataclass(frozen=True)
class Identifier:
    """One extracted identifier: its family, normalised value, and raw match."""

    kind: IdentifierKind
    value: str
    raw: str


# ``<record-group>_<box/folder>`` finding-aid location. The trailing boundary
# (``_`` or a word break) keeps this pinned to the ``RG_ITEM_…`` title shape.
_RG_FINDING_AID_RE = re.compile(r"\b(\d{2,3})_(\d{3,})(?:_|\b)")

# FBI headquarters file, optionally with a serial suffix (…-42).
_FBI_FILE_RE = re.compile(r"\b(\d{1,3}-HQ-\d{3,7}(?:-\d{1,5})?)\b", re.IGNORECASE)

# CIA CREST document IDs always start ``CIA-RDP`` (our own ``CIA-UAP-…`` card
# labels deliberately do not match).
# NOTE: no trailing `[0-9A-Z]*` after `{2,}` — two adjacent unbounded
# quantifiers over the same class backtrack quadratically on a failing
# match (3.1s at 16k chars), and this runs over externally-controlled
# government CSV description/title text.
_CIA_CREST_RE = re.compile(r"\bCIA-RDP[0-9A-Z]{2,}(?:-\d{1,3})?\b", re.IGNORECASE)

# Project Blue Book, then a case number nearby.
_BLUE_BOOK_RE = re.compile(
    r"blue\s*book\b[^.\n]{0,40}?\bcase\s+(?:no\.?\s*)?(\d{1,6})\b", re.IGNORECASE
)

# A number in an explicit NAID context — the only shape accepted as a NAID.
_NAID_CONTEXT_RE = re.compile(
    r"(?:naid|national\s+archives\s+identifier|catalog\.archives\.gov/id/)"
    r"\s*[:#]?\s*(\d{3,10})",
    re.IGNORECASE,
)


def rg_finding_aid_numbers(text: str) -> set[str]:
    """Return every box/folder number that appears as a record-group location.

    These are the numbers the NAID guard forbids: ``255_413270_…`` yields
    ``{"413270"}``. Both the record group and the box/folder number are
    collected, since either resolved as a NAID is a false positive.
    """
    numbers: set[str] = set()
    for match in _RG_FINDING_AID_RE.finditer(text or ""):
        numbers.add(match.group(1))
        numbers.add(match.group(2))
    return numbers


def is_rg_finding_aid_token(text: str) -> bool:
    """True iff ``text`` contains a ``<record-group>_<box/folder>_…`` token."""
    return _RG_FINDING_AID_RE.search(text or "") is not None


def _dedup(idents: list[Identifier]) -> list[Identifier]:
    """Drop duplicate (kind, value) pairs, preserving first-seen order."""
    seen: set[tuple[IdentifierKind, str]] = set()
    out: list[Identifier] = []
    for ident in idents:
        key = (ident.kind, ident.value)
        if key not in seen:
            seen.add(key)
            out.append(ident)
    return out


def extract_fbi_files(text: str) -> list[Identifier]:
    """Extract FBI file / serial numbers (e.g. ``62-HQ-83894``)."""
    return _dedup(
        [
            Identifier(IdentifierKind.FBI_FILE, m.group(1).upper(), m.group(1))
            for m in _FBI_FILE_RE.finditer(text or "")
        ]
    )


def extract_crest(text: str) -> list[Identifier]:
    """Extract CIA CREST ``CIA-RDP…`` document identifiers."""
    return _dedup(
        [
            Identifier(IdentifierKind.CIA_CREST, m.group(0).upper(), m.group(0))
            for m in _CIA_CREST_RE.finditer(text or "")
        ]
    )


def extract_blue_book(text: str) -> list[Identifier]:
    """Extract Project Blue Book case numbers (a named mention alone is not one)."""
    return _dedup(
        [
            Identifier(IdentifierKind.BLUE_BOOK_CASE, m.group(1), m.group(0))
            for m in _BLUE_BOOK_RE.finditer(text or "")
        ]
    )


def extract_naids(text: str) -> list[Identifier]:
    """Extract genuine NAIDs, refusing any record-group finding-aid number.

    Only a number in an explicit NAID context is a candidate, and any candidate
    that also appears as a record-group finding-aid location in the same text is
    dropped — the guard that keeps ``255_413270_…`` off NARA's catalog.
    """
    forbidden = rg_finding_aid_numbers(text)
    out: list[Identifier] = []
    for match in _NAID_CONTEXT_RE.finditer(text or ""):
        naid = match.group(1)
        if naid in forbidden:
            continue
        out.append(Identifier(IdentifierKind.NAID, naid, naid))
    return _dedup(out)


def extract_identifiers(card: dict[str, Any]) -> list[Identifier]:
    """Extract every resolvable identifier from a card's text fields.

    Title, description and asset filename are scanned together so an identifier
    stated in any of them is found; the NAID guard runs over the whole blob so a
    record-group number in the title still shields a matching NAID elsewhere.
    """
    text = " ".join(
        str(card.get(field) or "") for field in ("title", "description", "asset_filename")
    )
    idents: list[Identifier] = []
    idents.extend(extract_fbi_files(text))
    idents.extend(extract_crest(text))
    idents.extend(extract_blue_book(text))
    idents.extend(extract_naids(text))
    return _dedup(idents)
