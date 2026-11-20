"""How the tranche-diff receipt carries ``date_unresolved`` rows.

``year_normalize`` leaves a 2-digit year as upstream gave it when no stored
value or own-row evidence fixes the century; this module attaches those rows
to the receipt and renders its labelled worklist section, so the operator
sees them before approving. Both are absent when there are none, so a
receipt without unresolved dates keeps its prior shape byte for byte.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pursue_index.scrape.year_normalize import Unresolved

__all__ = ["attach_unresolved", "unresolved_md_parts", "unresolved_summary_line"]


def attach_unresolved(diff: dict[str, Any], dates: Mapping[str, list[Unresolved]]
                      ) -> dict[str, Any]:
    """Add ``date_unresolved`` (rows + a summary count) to a tranche diff,
    only when there are any; returns ``diff``."""
    for key, rows in dates.items():
        diff["summary"][key] = len(rows)
        diff[key] = rows
    return diff


def _cell(value: Any) -> str:
    """Upstream-derived text made safe for one markdown table cell."""
    return " ".join(str(value).split()).replace("|", "\\|").replace("`", "")[:80]


def unresolved_summary_line(summary: Mapping[str, Any]) -> str:
    """The receipt's summary bullet; empty when no row is unresolved."""
    if "date_unresolved" not in summary:
        return ""
    return f"- **{summary['date_unresolved']}** dates unresolved (2-digit year, manual review)\n"


def unresolved_md_parts(diff: Mapping[str, Any]) -> list[str]:
    """The receipt's labelled ``date_unresolved`` section; ``[]`` when absent."""
    if "date_unresolved" not in diff:
        return []
    rows = ["| card_id | field | upstream value | reason |", "|---|---|---|---|"]
    rows += [f"| `{_cell(r['card_id'])}` | {_cell(r['field'])} | `{_cell(r['raw'])}` | "
             f"{_cell(r['reason'])} |" for r in diff["date_unresolved"]]
    return ["## Date unresolved (2-digit year left as upstream gave it — MANUAL REVIEW)", "",
            "\n".join(rows) + "\n"]
