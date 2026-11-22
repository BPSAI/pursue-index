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

import html
import re
from collections.abc import Mapping
from typing import Any

from pursue_index.scrape.year_normalize import DateReport
from pursue_index.scrape.year_normalize_md import cell as _cell
from pursue_index.scrape.year_normalize_md import date_md_parts
from pursue_index.text_safety import neutralize

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


_MAX_DECODE_PASSES = 256
# Any "scheme://", plus "mailto:" and a leading "www.", is a bare autolink.
_SCHEME_SLASHES = re.compile(r"([a-z][a-z0-9+.\-]*):/{2}", re.I)
_MAILTO = re.compile(r"(mailto):", re.I)
_WWW = re.compile(r"\b(www)\.", re.I)
# "GH-123" is an issue reference; "#123" and "owner/repo#123" end in "#".
_GH_REF = re.compile(r"\b(gh)-(?=\d)", re.I)


def _decoded(value: Any) -> str:
    """``value`` with HTML entities decoded until the text stops changing, so a
    nested ``&amp;amp;#64;`` is judged as the ``@`` it eventually renders as.

    Every pass that changes the text shortens it, so the loop ends; the pass cap
    only bounds the cost of a hostile value, and ``_inert`` escapes any ``&`` left over.
    """
    text = "" if value is None else str(value)
    for _ in range(min(len(text), _MAX_DECODE_PASSES)):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def _inert(value: Any, limit: int = 80) -> str:
    """Upstream-derived text for a verdict-summary line, which is posted as an
    issue comment: entities decoded first, then table-safe (``cell``), no
    backticks or angle brackets, no live @-mention, no bare autolink
    (``scheme://``, ``mailto:``, ``www.``: one separator becomes its fullwidth
    form), no ``#123``/``GH-123`` cross-reference, backslashes then square
    brackets escaped so no link can form, and any remaining ``&`` escaped so no
    entity can re-form when the comment is rendered."""
    text = neutralize(_cell(_decoded(value), limit))
    text = _SCHEME_SLASHES.sub(lambda m: f"{m.group(1)}:\uff0f\uff0f", text)
    text = _MAILTO.sub(lambda m: f"{m.group(1)}\uff1a", text)
    text = _WWW.sub(lambda m: f"{m.group(1)}\uff0e", text)
    text = _GH_REF.sub(lambda m: f"{m.group(1)}\uff0d", text)
    text = text.replace("#", "\uff03")
    text = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return text.replace("&", "&amp;")


def _row_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [f"  * `{_inert(r['card_id'])}` {_inert(r.get('title'), 120)} — {_inert(r['field'], 40)} "
            f"`{_inert(r['raw'])}` ({_inert(r['reason'], 120)})" for r in rows]
