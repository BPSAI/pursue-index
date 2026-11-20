"""Restore 4-digit years on upstream's 2-digit raw dates.

Upstream CSV ``bae7455d`` switched raw ``Release Date`` / ``Incident Date``
from ``1/18/1957`` to ``1/18/57``. The snapshot generator normalizes them
back so the promoted manifest keeps 4-digit years; the per-value rules are
in ``year_resolve`` (stored prior value, then the row's own evidence, then
-- for ``release_date`` only -- the release window). Nothing is guessed: a
value no rule fixes stays as upstream gave it and is reported UNRESOLVED.

Only ``release_date`` and ``incident_date`` are touched; 4-digit and empty
values pass through. A field the prior manifest carries only in 2-digit
form (every snapshot before ``92b3``) has no 4-digit convention to keep: it
passes through unflagged, and the count of such values is reported. A
rewritten row keeps upstream's string in ``raw`` under the CSV column name,
and a row already rewritten is re-resolved from that string, so running the
normalization on a normalized manifest reproduces the same report. Pure:
inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pursue_index.scrape.types import CardMetadata
from pursue_index.scrape.year_resolve import (
    TWO_DIGIT,
    Window,
    release_window,
    resolve_value,
    two_digit_fields,
)

__all__ = ["DateReport", "normalize_cards", "normalize_manifest_dict", "normalize_rows"]

# field -> the upstream CSV column it is parsed from (csv_fetcher).
_FIELDS = {"release_date": "Release Date", "incident_date": "Incident Date"}


@dataclass
class DateReport:
    """What the normalization did, for the receipt and the summaries.

    ``considered`` is True when any new row carried a 2-digit-year value.
    ``window`` is the release window, set only when a row reached that rule.
    """

    unresolved: list[dict[str, Any]] = field(default_factory=list)
    window_rows: list[dict[str, Any]] = field(default_factory=list)
    window: Window | None = None
    passed_through: int = 0
    considered: bool = False


def _upstream(row: Mapping[str, Any], fld: str) -> str | None:
    """The 2-digit value upstream gave, from ``raw`` on a rewritten row."""
    for value in ((row.get("raw") or {}).get(_FIELDS[fld]), row.get(fld)):
        if isinstance(value, str) and TWO_DIGIT.match(value):
            return value
    return None


def _stored_values(prior_rows: Sequence[Mapping[str, Any]]) -> dict[tuple[Any, str], list[str]]:
    """``(card_id, field) -> non-empty stored values``, over every row of a
    card_id group (upstream duplicates card_ids; they are never deduped)."""
    out: dict[tuple[Any, str], list[str]] = {}
    for row in prior_rows:
        for fld in _FIELDS:
            value = row.get(fld)
            if isinstance(value, str) and value.strip():
                out.setdefault((row.get("card_id"), fld), []).append(value)
    return out


def _entry(row: Mapping[str, Any], fld: str, raw: str) -> dict[str, Any]:
    return {"card_id": row.get("card_id"), "title": row.get("title"), "field": fld, "raw": raw}


def _row_update(row: Mapping[str, Any], fields: Sequence[str], stored: Mapping,
                window: Window, report: DateReport) -> dict[str, Any]:
    update: dict[str, Any] = {}
    for fld in fields:
        raw = _upstream(row, fld)
        if raw is None:
            continue
        res = resolve_value(raw, row, fld, stored.get((row.get("card_id"), fld), []), window)
        if res.evidence == "release-window" or res.reason == "outside_release_window":
            report.window = window
        if res.value is None:
            report.unresolved.append({**_entry(row, fld, raw), "reason": res.reason})
            continue
        update[fld] = res.value
        update.setdefault("raw", dict(row.get("raw") or {}))[_FIELDS[fld]] = raw
        if res.evidence == "release-window":
            report.window_rows.append({**_entry(row, fld, raw), "value": res.value,
                                       "evidence": res.evidence})
    return update


def _updates(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]],
             fetch_year: int | None) -> tuple[list[dict[str, Any]], DateReport]:
    report = DateReport()
    skipped = two_digit_fields(prior_rows, list(_FIELDS))
    fields = [f for f in _FIELDS if f not in skipped]
    stored = _stored_values(prior_rows)
    window = release_window(prior_rows, fetch_year)
    updates = []
    for row in rows:
        seen = [f for f in _FIELDS if _upstream(row, f) is not None]
        report.considered = report.considered or bool(seen)
        report.passed_through += sum(1 for f in seen if f in skipped)
        updates.append(_row_update(row, fields, stored, window, report))
    return updates, report


def normalize_rows(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]],
                   fetch_year: int | None = None) -> tuple[list[dict[str, Any]], DateReport]:
    """Normalize JSON-shaped manifest rows against the prior manifest's rows.

    ``fetch_year`` (the new manifest's fetch year) is the release window's
    upper bound; without it the window rule never applies.
    """
    updates, report = _updates(rows, prior_rows, fetch_year)
    return [{**row, **upd} for row, upd in zip(rows, updates, strict=True)], report


def _year(fetched_at: Any) -> int | None:
    if isinstance(fetched_at, datetime):
        return fetched_at.year
    try:
        return datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00")).year
    except ValueError:
        return None


def normalize_manifest_dict(new: Mapping[str, Any], prior: Mapping[str, Any]
                            ) -> tuple[dict[str, Any], DateReport]:
    """A JSON manifest with its cards normalized against ``prior``'s; the
    window's upper bound is the year of ``new['fetched_at']``."""
    cards, report = normalize_rows(new.get("cards", []), prior.get("cards", []),
                                   _year(new.get("fetched_at")))
    return {**new, "cards": cards}, report


def normalize_cards(cards: Sequence[CardMetadata], prior_cards: Sequence[CardMetadata],
                    fetched_at: datetime | None = None
                    ) -> tuple[list[CardMetadata], DateReport]:
    """``normalize_rows`` over ``CardMetadata``; unchanged cards are returned as-is."""
    rows = [c.model_dump(mode="json") for c in cards]
    prior = [c.model_dump(mode="json") for c in prior_cards]
    updates, report = _updates(rows, prior, _year(fetched_at) if fetched_at else None)
    out = [c.model_copy(update=upd) if upd else c for c, upd in zip(cards, updates, strict=True)]
    return out, report
