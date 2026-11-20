"""Restore 4-digit years on upstream's 2-digit raw dates.

Upstream CSV ``bae7455d`` switched raw ``Release Date`` / ``Incident Date``
from ``1/18/1957`` to ``1/18/57``. The snapshot generator normalizes them
back so the promoted manifest keeps 4-digit years, without ever guessing a
century:

* a card_id already in the prior manifest gets the 4-digit value stored
  there, when the group's non-empty stored values agree and the one value
  has the same month, day and last two year digits; otherwise UNRESOLVED;
* a row with no stored value takes its century only from the row's own
  4-digit ``display_date`` (same month, day, 2-digit year) or -- for
  ``incident_date`` only -- a 4-digit year in its ``title`` /
  ``asset_filename`` whose last two digits match. One distinct year
  resolves; none or several is UNRESOLVED.

Only ``release_date`` and ``incident_date`` are touched; 4-digit and empty
values pass through. A field the prior manifest carries only in 2-digit
form (every snapshot before ``92b3``) has no 4-digit convention to keep:
it passes through unflagged, so historical receipts replay unchanged. A rewritten row keeps upstream's string in ``raw``
under the CSV column name, so the change stays auditable. Pure: inputs are
never mutated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pursue_index.scrape.types import CardMetadata

__all__ = ["Unresolved", "normalize_cards", "normalize_manifest_dict", "normalize_rows"]

# field -> the upstream CSV column it is parsed from (csv_fetcher).
_FIELDS = {"release_date": "Release Date", "incident_date": "Incident Date"}
_TWO_DIGIT = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2})\s*$")
_FOUR_DIGIT_MDY = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_FOUR_DIGIT_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_YEAR_IN_TEXT = re.compile(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)")

Unresolved = dict[str, str]


def _mdy(value: Any) -> tuple[int, int, int] | None:
    """``(month, day, 4-digit year)`` from a 4-digit M/D/YYYY or ISO date."""
    if not isinstance(value, str):
        return None
    if m := _FOUR_DIGIT_MDY.match(value):
        return int(m[1]), int(m[2]), int(m[3])
    if m := _FOUR_DIGIT_ISO.match(value):
        return int(m[2]), int(m[3]), int(m[1])
    return None


def _agrees(value: Any, month: int, day: int, yy: int) -> int | None:
    """The 4-digit year of ``value`` if it is the same date as M/D/YY."""
    parsed = _mdy(value)
    if parsed and parsed[:2] == (month, day) and parsed[2] % 100 == yy:
        return parsed[2]
    return None


def _from_prior(stored: list[str], month: int, day: int, yy: int) -> tuple[str | None, str]:
    """Restore from the group's stored values: ``(value, '')`` or ``(None, reason)``."""
    distinct = list(dict.fromkeys(s.strip() for s in stored))
    if len(distinct) > 1:
        return None, "prior_disagree"
    if _agrees(distinct[0], month, day, yy) is None:
        return None, "prior_mismatch"
    return distinct[0], ""


def _evidence_years(row: Mapping[str, Any], field: str, month: int, day: int,
                    yy: int) -> set[int]:
    """Candidate 4-digit years from the row's own metadata."""
    years: set[int] = set()
    from_display = _agrees(row.get("display_date"), month, day, yy)
    if from_display is not None:
        years.add(from_display)
    if field == "incident_date":
        for text in (row.get("title"), row.get("asset_filename")):
            for y in _YEAR_IN_TEXT.findall(text or ""):
                if int(y) % 100 == yy:
                    years.add(int(y))
    return years


def _from_row(row: Mapping[str, Any], field: str, parts: tuple[str, str, str]
              ) -> tuple[str | None, str]:
    """Derive the century from the row's own metadata, never a guess."""
    month, day, yy = (int(p) for p in parts)
    years = _evidence_years(row, field, month, day, yy)
    if not years:
        return None, "no_century_evidence"
    if len(years) > 1:
        return None, "ambiguous_evidence"
    return f"{parts[0]}/{parts[1]}/{years.pop()}", ""


def _resolve(row: Mapping[str, Any], field: str, stored: list[str]
             ) -> tuple[str | None, str]:
    """``(4-digit value, '')``, ``(None, reason)``, or ``(None, '')`` when
    the value is not a 2-digit-year date and passes through."""
    m = _TWO_DIGIT.match(row.get(field) or "")
    if m is None:
        return None, ""
    if stored:
        return _from_prior(stored, int(m[1]), int(m[2]), int(m[3]))
    return _from_row(row, field, (m[1], m[2], m[3]))


def _stored_values(prior_rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """``(card_id, field) -> non-empty stored values``, over every row of a
    card_id group (upstream duplicates card_ids; they are never deduped)."""
    out: dict[tuple[str, str], list[str]] = {}
    for row in prior_rows:
        for field in _FIELDS:
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                out.setdefault((row.get("card_id"), field), []).append(value)
    return out


def _two_digit_era(prior_rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """Fields the prior holds in 2-digit form and never in 4-digit M/D/YYYY."""
    def has(field: str, pattern: re.Pattern[str]) -> bool:
        return any(pattern.match(str(r.get(field) or "")) for r in prior_rows)
    return {f for f in _FIELDS if has(f, _TWO_DIGIT) and not has(f, _FOUR_DIGIT_MDY)}


def _updates(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]]
             ) -> tuple[list[dict[str, Any]], list[Unresolved]]:
    """Per-row ``{field: value, 'raw': {...}}`` updates plus the unresolved list."""
    stored = _stored_values(prior_rows)
    fields = {f: c for f, c in _FIELDS.items() if f not in _two_digit_era(prior_rows)}
    updates: list[dict[str, Any]] = []
    unresolved: list[Unresolved] = []
    for row in rows:
        update: dict[str, Any] = {}
        for field, column in fields.items():
            value, reason = _resolve(row, field, stored.get((row.get("card_id"), field), []))
            if value is not None:
                update[field] = value
                update.setdefault("raw", dict(row.get("raw") or {}))[column] = row[field]
            elif reason:
                unresolved.append({"card_id": row.get("card_id"), "field": field,
                                   "raw": row[field], "reason": reason})
        updates.append(update)
    return updates, unresolved


def normalize_rows(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]]
                   ) -> tuple[list[dict[str, Any]], list[Unresolved]]:
    """Normalize JSON-shaped manifest rows against the prior manifest's rows.

    Returns ``(rows, unresolved)``; each unresolved entry is
    ``{card_id, field, raw, reason}``.
    """
    updates, unresolved = _updates(rows, prior_rows)
    return [{**row, **upd} for row, upd in zip(rows, updates, strict=True)], unresolved


def normalize_manifest_dict(new: Mapping[str, Any], prior: Mapping[str, Any]
                            ) -> tuple[dict[str, Any], dict[str, list[Unresolved]]]:
    """A JSON manifest with its cards normalized against ``prior``'s, plus
    ``{"date_unresolved": [...]}`` -- or ``{}`` when none, so a receipt
    without unresolved dates keeps its prior shape."""
    cards, unresolved = normalize_rows(new.get("cards", []), prior.get("cards", []))
    return {**new, "cards": cards}, ({"date_unresolved": unresolved} if unresolved else {})


def normalize_cards(cards: Sequence[CardMetadata], prior_cards: Sequence[CardMetadata]
                    ) -> tuple[list[CardMetadata], list[Unresolved]]:
    """``normalize_rows`` over ``CardMetadata``; unchanged cards are returned as-is."""
    rows = [c.model_dump(mode="json") for c in cards]
    prior = [c.model_dump(mode="json") for c in prior_cards]
    updates, unresolved = _updates(rows, prior)
    out = [c.model_copy(update=upd) if upd else c for c, upd in zip(cards, updates, strict=True)]
    return out, unresolved

