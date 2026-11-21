"""How a ``DateReport`` reaches the tranche-diff receipt and the summaries.

Receipt keys (each present only when it has something to say, so a receipt
for a manifest without 2-digit years keeps its earlier shape byte for byte):

* ``date_unresolved`` + ``summary.date_unresolved`` -- values no rule fixed,
  flagged for the first time;
* ``date_open`` + ``summary.date_open`` -- values still unresolved that a
  prior marker already carries (same upstream value): open, not new;
* ``date_manual_rows`` + ``summary.date_manual_resolved`` -- values a manual
  overlay entry (``date_resolutions``) resolved, evidence ``manual``;
* ``date_acknowledged`` + ``summary.date_acknowledged`` -- values an
  acknowledged-unknown overlay entry covers (``{card_id, title, field, raw,
  reason, curator, approved_at}``): no date written, no review forced;
* ``release_window`` (``{lower, upper, source}``) + ``release_window_rows``
  (each with ``evidence: release-window``) + ``summary.release_window_resolved``.

The count of 2-digit values passed through because the prior holds that
field only in 2-digit form is NOT a receipt key: receipts are replayed byte
for byte. It goes only to the verdict summary (``verdict_date_lines``) and
the scripts' stdout. The source CSV's data-row number is not shown: the
parse does not keep it. The worklist's sections (``date_md_parts``) are in ``year_normalize_md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pursue_index.scrape.year_normalize import DateReport
from pursue_index.scrape.year_normalize_md import cell as _cell
from pursue_index.scrape.year_normalize_md import date_md_parts

__all__ = ["attach_date_report", "date_md_parts", "date_summary_lines", "verdict_date_lines"]

WINDOW_SOURCE = ("lower: earliest 4-digit release_date year in the prior manifest; "
                 "upper: year of the new manifest's fetched_at")


def attach_date_report(diff: dict[str, Any], report: DateReport) -> dict[str, Any]:
    """Add the report's receipt keys to a tranche diff; returns ``diff``."""
    s = diff["summary"]
    if report.unresolved:
        s["date_unresolved"] = len(report.unresolved)
        diff["date_unresolved"] = report.unresolved
    if report.open:
        s["date_open"] = len(report.open)
        diff["date_open"] = report.open
    if report.manual_rows:
        s["date_manual_resolved"] = len(report.manual_rows)
        diff["date_manual_rows"] = report.manual_rows
    if report.acknowledged:
        s["date_acknowledged"] = len(report.acknowledged)
        diff["date_acknowledged"] = report.acknowledged
    if report.window is not None:
        s["release_window_resolved"] = len(report.window_rows)
        diff["release_window"] = {"lower": report.window.lower, "upper": report.window.upper,
                                  "source": WINDOW_SOURCE}
        diff["release_window_rows"] = report.window_rows
    return diff


def date_summary_lines(summary: Mapping[str, Any]) -> str:
    """The receipt's summary bullets; empty when the receipt has none."""
    out = ""
    if "date_unresolved" in summary:
        out += (f"- **{summary['date_unresolved']}** dates unresolved "
                "(2-digit year, manual review)\n")
    if "date_open" in summary:
        out += (f"- **{summary['date_open']}** dates still open from an earlier tranche "
                "(2-digit year, manual review)\n")
    if "date_manual_resolved" in summary:
        out += f"- **{summary['date_manual_resolved']}** dates resolved by a manual entry\n"
    if "date_acknowledged" in summary:
        out += (f"- **{summary['date_acknowledged']}** dates acknowledged unknown "
                "(no date written, no review forced)\n")
    if "release_window_resolved" in summary:
        out += (f"- **{summary['release_window_resolved']}** release dates resolved by "
                "the release window\n")
    return out


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
                     "(2-digit year; stored value kept, else empty)")
        lines += _row_lines(report.unresolved)
    if report.open:
        lines.append(f"* date_unresolved still open (carried, not new): {len(report.open)}")
        lines += _row_lines(report.open)
    if report.manual_rows:
        lines.append(f"* resolved by a manual entry: {len(report.manual_rows)}")
    if report.acknowledged:
        lines.append(f"* date acknowledged unknown: {len(report.acknowledged)} "
                     "(no date written, no review forced)")
        lines += _row_lines(report.acknowledged)
    return "\n".join(lines) + "\n"


def _row_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [f"  * `{_cell(r['card_id'])}` {_cell(r.get('title'), 120)} — {r['field']} "
            f"`{_cell(r['raw'])}` ({_cell(r['reason'], 120)})" for r in rows]
