"""How a ``DateReport`` reaches the tranche-diff receipt and the summaries.

Receipt keys (each present only when it has something to say, so a receipt
for a manifest without 2-digit years keeps its earlier shape byte for byte):

* ``date_unresolved`` + ``summary.date_unresolved`` -- values no rule fixed;
* ``release_window`` (``{lower, upper, source}``) + ``release_window_rows``
  (each with ``evidence: release-window``) + ``summary.release_window_resolved``.

The count of 2-digit values passed through because the prior holds that
field only in 2-digit form is NOT a receipt key: receipts are replayed byte
for byte. It goes only to the verdict summary (``verdict_date_lines``) and
the scripts' stdout. The source CSV's data-row number is not shown: the
parse does not keep it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pursue_index.scrape.year_normalize import DateReport

__all__ = ["attach_date_report", "date_md_parts", "date_summary_lines", "verdict_date_lines"]

WINDOW_SOURCE = ("lower: earliest 4-digit release_date year in the prior manifest; "
                 "upper: year of the new manifest's fetched_at")


def attach_date_report(diff: dict[str, Any], report: DateReport) -> dict[str, Any]:
    """Add the report's receipt keys to a tranche diff; returns ``diff``."""
    s = diff["summary"]
    if report.unresolved:
        s["date_unresolved"] = len(report.unresolved)
        diff["date_unresolved"] = report.unresolved
    if report.window is not None:
        s["release_window_resolved"] = len(report.window_rows)
        diff["release_window"] = {"lower": report.window.lower, "upper": report.window.upper,
                                  "source": WINDOW_SOURCE}
        diff["release_window_rows"] = report.window_rows
    return diff


def _cell(value: Any, limit: int = 80) -> str:
    """Upstream-derived text made safe for one markdown table cell."""
    return " ".join(str(value or "").split()).replace("|", "\\|").replace("`", "")[:limit]


def date_summary_lines(summary: Mapping[str, Any]) -> str:
    """The receipt's summary bullets; empty when the receipt has none."""
    out = ""
    if "date_unresolved" in summary:
        out += (f"- **{summary['date_unresolved']}** dates unresolved "
                "(2-digit year, manual review)\n")
    if "release_window_resolved" in summary:
        out += (f"- **{summary['release_window_resolved']}** release dates resolved by "
                "the release window\n")
    return out


def _unresolved_table(rows: list[dict[str, Any]]) -> str:
    out = ["| card_id | title | field | upstream value | reason |", "|---|---|---|---|---|"]
    out += [f"| `{_cell(r['card_id'])}` | {_cell(r.get('title'), 120)} | {_cell(r['field'])} "
            f"| `{_cell(r['raw'])}` | {_cell(r['reason'])} |" for r in rows]
    return "\n".join(out) + "\n"


def _window_parts(diff: Mapping[str, Any]) -> list[str]:
    w = diff["release_window"]
    rows = ["| card_id | title | upstream value | restored | evidence |", "|---|---|---|---|---|"]
    rows += [f"| `{_cell(r['card_id'])}` | {_cell(r.get('title'), 120)} | `{_cell(r['raw'])}` "
             f"| `{_cell(r['value'])}` | {_cell(r['evidence'])} |"
             for r in diff["release_window_rows"]]
    return [f"## Release window ({w['lower']}-{w['upper']})", "", f"_{w['source']}._", "",
            "\n".join(rows) + "\n"]


def date_md_parts(diff: Mapping[str, Any]) -> list[str]:
    """The receipt's labelled date sections; ``[]`` when it has none."""
    parts: list[str] = []
    if "date_unresolved" in diff:
        parts += ["## Date unresolved (2-digit year left as upstream gave it — MANUAL REVIEW)",
                  "", _unresolved_table(diff["date_unresolved"])]
    if "release_window" in diff:
        parts += _window_parts(diff)
    return parts


def verdict_date_lines(report: DateReport) -> str:
    """The verdict summary's date lines; empty when no 2-digit year was seen."""
    if not report.considered:
        return ""
    lines = [f"* 2-digit priors passed through: {report.passed_through}"]
    if report.window is not None:
        lines.append(f"* release window {report.window.lower}-{report.window.upper}: "
                     f"{len(report.window_rows)} release date(s) resolved")
    if report.unresolved:
        lines.append(f"* date_unresolved: {len(report.unresolved)} "
                     "(2-digit year left as upstream gave it)")
        lines += [f"  * `{_cell(r['card_id'])}` {_cell(r.get('title'), 120)} — {r['field']} "
                  f"`{_cell(r['raw'])}` ({r['reason']})" for r in report.unresolved]
    return "\n".join(lines) + "\n"
