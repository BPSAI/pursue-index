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
    assert "@" not in text.replace("\uff20", "")
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


def test_field_name_is_neutralized() -> None:
    for hostile in ("@x", "[a](http://e)", "<b>"):
        text = _lines(unresolved=[_row(field=hostile)])
        _assert_inert(text)


def _inert_text(value: str) -> str:
    from pursue_index.scrape.year_normalize_report import _inert

    return _inert(value)


def test_entity_encoded_mentions_are_neutralized() -> None:
    for hostile in ("&#64;someone", "&commat;someone", "&#x40;someone"):
        out = _inert_text(hostile)
        assert "@" not in out.replace("\uff20", ""), hostile
        assert "&#64" not in out and "&commat" not in out
        assert "someone" in out


def test_bare_autolinks_are_broken() -> None:
    for url in ("http://evil.example/x", "https://evil.example/x", "HTTPS://evil.example"):
        out = _inert_text(f"see {url} now")
        assert "://" not in out, url
        assert "evil.example" in out


def test_entity_encoded_autolink_is_broken() -> None:
    assert "://" not in _inert_text("&#104;ttp&colon;//evil.example")


def test_backslash_before_bracket_cannot_unescape_it() -> None:
    for hostile in (r"\[a](http://e)", r"\\[a](http://e)", r"\\\[a](http://e)"):
        out = _inert_text(hostile)
        # Every "[" is preceded by an odd run of backslashes (so it is literal).
        for m in __import__("re").finditer(r"(\\*)\[", out):
            assert len(m.group(1)) % 2 == 1, (hostile, out)
        for m in __import__("re").finditer(r"(\\*)\]", out):
            assert len(m.group(1)) % 2 == 1, (hostile, out)
        assert "://" not in out
