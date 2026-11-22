"""The verdict summary is posted as an issue comment, so upstream-derived
titles and values in its date lines carry no @-mention, link or HTML syntax."""

from __future__ import annotations

from pursue_index.scrape.year_normalize import DateReport
from pursue_index.scrape.year_normalize_report import verdict_date_lines

_HOSTILE = "ping @someone [x](http://e) <b>bold</b>"


def _row(**over):
    row = {"card_id": "abc123", "title": _HOSTILE, "field": "release_date",
           "raw": "5/8/26", "reason": "no rule"}
    return {**row, **over}


def _lines(**report_kwargs) -> str:
    report = DateReport(considered=1, **report_kwargs)
    return verdict_date_lines(report)


def _assert_inert(text: str) -> None:
    assert "@" not in text.replace("＠", "")
    assert "<" not in text and ">" not in text
    assert "](http" not in text.replace("\\]", "")  # a backslash-escaped bracket is literal
    assert "[" not in text.replace("\\[", "")


def test_unresolved_row_title_is_neutralized() -> None:
    text = _lines(unresolved=[_row()])
    _assert_inert(text)
    assert "someone" in text  # still readable, only defanged


def test_open_and_acknowledged_rows_are_neutralized() -> None:
    text = _lines(open=[_row()], acknowledged=[_row()])
    _assert_inert(text)


def test_values_and_reason_are_neutralized() -> None:
    text = _lines(unresolved=[_row(raw=_HOSTILE, reason=_HOSTILE, card_id=_HOSTILE)])
    _assert_inert(text)
