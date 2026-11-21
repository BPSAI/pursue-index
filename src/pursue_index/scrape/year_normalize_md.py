"""The tranche-diff worklist's date sections (``year_normalize_report``).

Each section is present only when the receipt carries its key:
``date_unresolved`` / ``date_open`` (with how to resolve them and one
paste-ready overlay entry of each kind per row), ``date_acknowledged``,
``date_manual_rows`` and ``release_window``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pursue_index.scrape.date_resolutions import (
    ACK_ENTRY_SHAPE,
    ACKNOWLEDGED,
    DATE_RESOLUTIONS_FILE,
    ENTRY_SHAPE,
)

__all__ = ["cell", "date_md_parts"]


def cell(value: Any, limit: int = 80) -> str:
    """Upstream-derived text made safe for one markdown table cell."""
    return " ".join(str(value or "").split()).replace("|", "\\|").replace("`", "")[:limit]


def _unresolved_table(rows: list[dict[str, Any]], since: bool = False) -> str:
    head = "| card_id | title | field | upstream value | reason |"
    out = [head + (" first flagged in |" if since else ""),
           "|---|---|---|---|---|" + ("---|" if since else "")]
    out += [f"| `{cell(r['card_id'])}` | {cell(r.get('title'), 120)} | {cell(r['field'])} "
            f"| `{cell(r['raw'])}` | {cell(r['reason'])} |"
            + (f" `{cell(r.get('first_flagged_in'))[:12]}` |" if since else "") for r in rows]
    return "\n".join(out) + "\n"


_HOW_TO_RESOLVE = (
    f"_While a date is open the card keeps its stored 4-digit value, or is empty when there "
    f"is none. To resolve one, add an entry to "
    f"`{DATE_RESOLUTIONS_FILE}` (`{{\"entries\": [...]}}`), one per card_id and field: "
    f"`{ENTRY_SHAPE}`. The value's month, day and last two year digits must match the "
    "upstream value, or the row stays unresolved (`manual_mismatch`). To record that a "
    f"date stays unknown instead, add `{ACK_ENTRY_SHAPE}`: the field stays as it is and "
    "the row stops forcing review while upstream's value is unchanged._")


def _skeletons(rows: list[dict[str, Any]]) -> str:
    """Two paste-ready entries per row -- a value entry, month and day filled
    from upstream's value, and an acknowledged-unknown entry (2-digit dates
    and hex card_ids only, so nothing to escape)."""
    out = []
    for r in rows:
        raw = str(r["raw"]).strip()
        out.append("    " + json.dumps({"card_id": r["card_id"], "field": r["field"],
                                        "value": f"{raw.rsplit('/', 1)[0]}/YYYY",
                                        "curator": "<who>", "approved_at": "<ISO-8601 UTC>"}))
        out.append("    " + json.dumps({"card_id": r["card_id"], "field": r["field"],
                                        "value": None, "status": ACKNOWLEDGED,
                                        "reason": "<why it stays unknown>", "curator": "<who>",
                                        "approved_at": "<ISO-8601 UTC>",
                                        "upstream_value": raw}))
    return "```json\n" + ",\n".join(out) + "\n```\n"


def _acknowledged_table(rows: list[dict[str, Any]]) -> str:
    out = ["| card_id | title | field | upstream value | reason | curator | approved_at |",
           "|---|---|---|---|---|---|---|"]
    out += [f"| `{cell(r['card_id'])}` | {cell(r.get('title'), 120)} | {cell(r['field'])} "
            f"| `{cell(r['raw'])}` | {cell(r.get('reason'), 120)} | {cell(r.get('curator'))} "
            f"| {cell(r.get('approved_at'))} |" for r in rows]
    return "\n".join(out) + "\n"


def _manual_table(rows: list[dict[str, Any]]) -> str:
    out = ["| card_id | title | field | upstream value | restored | curator | approved_at |",
           "|---|---|---|---|---|---|---|"]
    out += [f"| `{cell(r['card_id'])}` | {cell(r.get('title'), 120)} | {cell(r['field'])} "
            f"| `{cell(r['raw'])}` | `{cell(r['value'])}` | {cell(r.get('curator'))} "
            f"| {cell(r.get('approved_at'))} |" for r in rows]
    return "\n".join(out) + "\n"


def _window_parts(diff: Mapping[str, Any]) -> list[str]:
    w = diff["release_window"]
    rows = ["| card_id | title | upstream value | restored | evidence |", "|---|---|---|---|---|"]
    rows += [f"| `{cell(r['card_id'])}` | {cell(r.get('title'), 120)} | `{cell(r['raw'])}` "
             f"| `{cell(r['value'])}` | {cell(r['evidence'])} |"
             for r in diff["release_window_rows"]]
    return [f"## Release window ({w['lower']}-{w['upper']})", "", f"_{w['source']}._", "",
            "\n".join(rows) + "\n"]


def date_md_parts(diff: Mapping[str, Any]) -> list[str]:
    """The receipt's labelled date sections; ``[]`` when it has none."""
    parts: list[str] = []
    if "date_unresolved" in diff:
        parts += ["## Date unresolved (2-digit year; stored value kept, else card field "
                  "empty — MANUAL REVIEW)", "", _unresolved_table(diff["date_unresolved"])]
    if "date_open" in diff:
        parts += ["## Date unresolved, still open (carried from an earlier tranche — "
                  "MANUAL REVIEW)", "", _unresolved_table(diff["date_open"], since=True)]
    if "date_unresolved" in diff or "date_open" in diff:
        parts += [_HOW_TO_RESOLVE, "", _skeletons([*diff.get("date_unresolved", []),
                                                   *diff.get("date_open", [])])]
    if "date_acknowledged" in diff:
        parts += ["## Date acknowledged unknown (2-digit year; stored value kept, else card "
                  "field empty — no date invented)", "",
                  _acknowledged_table(diff["date_acknowledged"])]
    if "date_manual_rows" in diff:
        parts += ["## Date resolved by a manual entry", "", _manual_table(diff["date_manual_rows"])]
    if "release_window" in diff:
        parts += _window_parts(diff)
    return parts
