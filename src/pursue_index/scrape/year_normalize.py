"""Restore 4-digit years on upstream's 2-digit raw dates.

Upstream CSV ``bae7455d`` switched raw ``Release Date`` / ``Incident Date``
from ``1/18/1957`` to ``1/18/57``. The snapshot generator normalizes them
back so the promoted manifest keeps 4-digit years; the per-value rules are
in ``year_resolve`` (a manual overlay entry, the stored prior value, then
the row's own evidence, then -- for ``release_date`` only -- the release
window). Nothing is guessed: a value no rule fixes is reported UNRESOLVED;
its field keeps the prior's stored 4-digit value unchanged, or is left
EMPTY when the prior stores none, so it never becomes a 2-digit prior;
``year_marker`` carries it as an open item across polls (reported under
``open``, not as a new flag, while upstream's value is unchanged).

Only ``release_date`` and ``incident_date`` are touched; 4-digit and empty
values pass through. A field the prior manifest carries only in 2-digit
form (every snapshot before ``92b3``) has no 4-digit convention to keep: it
passes through unflagged, and the count of such values is reported -- but
never for a field the prior marks open. A rewritten row keeps upstream's
string in ``raw`` under the CSV column name, and a row already rewritten is
re-resolved from that string, so running the normalization on a normalized
manifest reproduces the same report. Pure: inputs are never mutated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pursue_index.scrape.date_resolutions import Overlay
from pursue_index.scrape.types import CardMetadata
from pursue_index.scrape.year_marker import iso, prior_markers, with_markers
from pursue_index.scrape.year_outcome import (
    DateReport,
    RunContext,
    kept_value,
    paired_priors,
    record_resolved,
    record_unresolved,
)
from pursue_index.scrape.year_resolve import (
    TWO_DIGIT,
    release_window,
    resolve_value,
    two_digit_fields,
)

__all__ = ["DATE_FIELDS", "DateReport", "normalize_cards", "normalize_manifest_dict",
           "normalize_rows", "upstream_value"]

# field -> the upstream CSV column it is parsed from (csv_fetcher).
_FIELDS = {"release_date": "Release Date", "incident_date": "Incident Date"}
DATE_FIELDS = tuple(_FIELDS)


def upstream_value(row: Mapping[str, Any], fld: str) -> str | None:
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


def _row_update(row: Mapping[str, Any], fields: Sequence[str], ctx: RunContext,
                report: DateReport, paired: Mapping[str, Any] | None) -> dict[str, Any]:
    update: dict[str, Any] = {}
    raw_out = dict(row.get("raw") or {})
    markers: list[dict[str, Any]] = []
    for fld in fields:
        raw = upstream_value(row, fld)
        if raw is None:
            continue
        key = (row.get("card_id"), fld)
        stored, manual = ctx.stored.get(key, []), ctx.overlay.get(key)
        res = resolve_value(raw, row, fld, stored, ctx.window,
                            manual["value"] if manual else None)
        if res.evidence == "release-window" or res.reason == "outside_release_window":
            report.window = ctx.window
        raw_out[_FIELDS[fld]] = raw
        if res.value is None:
            update[fld] = kept_value(paired, fld)
            markers.append(record_unresolved(row, fld, raw, res.reason, ctx, report))
        else:
            update[fld] = res.value
            record_resolved(row, fld, raw, res, stored, ctx, report)
    raw_out = with_markers(raw_out, markers)
    if update or raw_out != (row.get("raw") or {}):
        update["raw"] = raw_out
    return update


def _updates(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]],
             fetch_year: int | None, overlay: Overlay | None, tranche: str | None,
             fetched_at: str | None) -> tuple[list[dict[str, Any]], DateReport]:
    report = DateReport()
    skipped = two_digit_fields(prior_rows, list(_FIELDS))
    ctx = RunContext(_stored_values(prior_rows), release_window(prior_rows, fetch_year),
               prior_markers(prior_rows), overlay or {}, tranche, fetched_at)
    updates = []
    for row, paired in zip(rows, paired_priors(rows, prior_rows), strict=True):
        # A field the prior marks open is never passed through.
        fields = [f for f in _FIELDS
                  if f not in skipped or (row.get("card_id"), f) in ctx.markers]
        seen = [f for f in _FIELDS if upstream_value(row, f) is not None]
        report.considered = report.considered or bool(seen)
        report.passed_through += sum(1 for f in seen if f not in fields)
        updates.append(_row_update(row, fields, ctx, report, paired))
    return updates, report


def normalize_rows(rows: Sequence[Mapping[str, Any]], prior_rows: Sequence[Mapping[str, Any]],
                   fetch_year: int | None = None, *, overlay: Overlay | None = None,
                   tranche: str | None = None, fetched_at: str | None = None
                   ) -> tuple[list[dict[str, Any]], DateReport]:
    """Normalize JSON-shaped manifest rows against the prior manifest's rows.

    ``fetch_year`` (the new manifest's fetch year) is the release window's
    upper bound; without it the window rule never applies. ``overlay`` is
    the manual resolutions (``date_resolutions``); ``tranche`` and
    ``fetched_at`` (the new manifest's ``csv_sha256`` and serialized fetch
    time) stamp a new flag's marker.
    """
    updates, report = _updates(rows, prior_rows, fetch_year, overlay, tranche, fetched_at)
    return [{**row, **upd} for row, upd in zip(rows, updates, strict=True)], report


def _year(fetched_at: Any) -> int | None:
    if isinstance(fetched_at, datetime):
        return fetched_at.year
    try:
        return datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00")).year
    except ValueError:
        return None


def normalize_manifest_dict(new: Mapping[str, Any], prior: Mapping[str, Any],
                            overlay: Overlay | None = None
                            ) -> tuple[dict[str, Any], DateReport]:
    """A JSON manifest with its cards normalized against ``prior``'s; the
    window's upper bound is the year of ``new['fetched_at']``."""
    cards, report = normalize_rows(new.get("cards", []), prior.get("cards", []),
                                   _year(new.get("fetched_at")), overlay=overlay,
                                   tranche=new.get("csv_sha256"),
                                   fetched_at=new.get("fetched_at"))
    return {**new, "cards": cards}, report


def normalize_cards(cards: Sequence[CardMetadata], prior_cards: Sequence[CardMetadata],
                    fetched_at: datetime | None = None, *, overlay: Overlay | None = None,
                    tranche: str | None = None) -> tuple[list[CardMetadata], DateReport]:
    """``normalize_rows`` over ``CardMetadata``; unchanged cards are returned as-is."""
    rows = [c.model_dump(mode="json") for c in cards]
    prior = [c.model_dump(mode="json") for c in prior_cards]
    updates, report = _updates(rows, prior, _year(fetched_at) if fetched_at else None,
                               overlay, tranche, iso(fetched_at))
    out = [c.model_copy(update=upd) if upd else c for c, upd in zip(cards, updates, strict=True)]
    return out, report
