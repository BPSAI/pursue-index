"""The verdict summary is posted as an issue comment, so upstream-derived
titles and values in its date lines carry no @-mention, link or HTML syntax."""

from __future__ import annotations

import html

from pursue_index.scrape.year_normalize import DateReport
from pursue_index.scrape.year_normalize_report import verdict_date_lines

_FW_AT = chr(0xFF20)
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


def _inert_text(value: str, limit: int = 80) -> str:
    from pursue_index.scrape.year_normalize_report import _inert

    return _inert(value, limit)


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


def _nest(inner: str, depth: int) -> str:
    """``inner`` (an entity body such as ``#64``) wrapped in ``depth`` extra layers of ``&amp;``."""
    return "&amp;" * (depth - 1) + "&" + inner + ";someone"


def _no_live_entity(out: str) -> None:
    import re

    # Whatever "&" survives is itself escaped, so no further decode can re-form an entity.
    assert not re.search(r"&(?!amp;)", out), out
    assert "@" not in out.replace(_FW_AT, "")


def test_nested_entities_of_every_depth_are_neutralized() -> None:
    for inner in ("#64", "#x40", "commat"):
        for depth in range(1, 7):
            out = _inert_text(_nest(inner, depth))
            _no_live_entity(out)
            assert "someone" in out, (inner, depth)


def test_four_level_nest_from_review_is_neutralized() -> None:
    out = _inert_text("&amp;amp;amp;#64;someone")
    _no_live_entity(out)
    assert _FW_AT + "someone" in out


def test_mixed_form_nests_are_neutralized() -> None:
    for hostile in ("&amp;#x26;#64;someone", "&#38;amp;#x40;someone", "&amp;&#35;64;someone",
                    "&#x26;amp;commat;someone"):
        _no_live_entity(_inert_text(hostile))


def test_nest_longer_than_the_decode_cap_is_still_inert() -> None:
    out = _inert_text("&amp;" * 5000 + "#64;someone", limit=100000)
    _no_live_entity(out)


def test_lone_ampersand_survives_as_an_escaped_ampersand() -> None:
    assert _inert_text("R&D") == "R&amp;D"


def test_other_autolinks_are_broken() -> None:
    for hostile in ("www.evil.example", "WWW.evil.example/x", "ftp://evil.example/x",
                    "mailto:a@evil.example", "MAILTO:x", "a@evil.example", "&#109;ailto&colon;a",
                    "file:///etc/passwd", "git+ssh://host/x"):
        out = _inert_text(f"see {hostile} now")
        assert "://" not in out, hostile
        assert "www." not in out.lower(), hostile
        assert "mailto:" not in out.lower(), hostile
        assert "@" not in out.replace(_FW_AT, ""), hostile
        assert "evil" in out or "mailto" in out.lower() or "etc" in out or "host" in out


def test_issue_and_pr_references_are_broken() -> None:
    import re

    for hostile in ("#123", "fixes #123", "GH-123", "gh-7", "owner/repo#123", "(#99)",
                    "&#35;123", "&amp;#35;123"):
        out = _inert_text(hostile)
        assert "#" not in out.replace("&#", ""), hostile
        assert not re.search(r"(?i)\bgh-\d", out), hostile
        assert re.search(r"\d", out), hostile  # still readable


def _split_row(row: str) -> list[str]:
    """Cells of a GFM table row: a pipe separates unless an odd run of backslashes escapes it."""
    import re

    parts = re.split(r"(?<!\\)((?:\\\\)*)\|", row)
    cells, cur = [], parts[0]
    for i in range(1, len(parts), 2):
        cur += parts[i]
        cells.append(cur)
        cur = parts[i + 1]
    cells.append(cur)
    return cells


def _render_literal(out: str) -> str:
    """What a markdown renderer shows for ``out``: escapes resolved, entities decoded."""
    import re

    return html.unescape(re.sub(r"\\([\\\[\]|])", r"\1", out))


def test_pipes_survive_the_table_cell_escape() -> None:
    value = r"a|b \| c \ d [a](http://e)"
    out = _inert_text(value)
    cells = _split_row(f"| x | {out} | y |")
    assert len(cells) == 5, (out, cells)  # leading and trailing empty strings plus three cells
    shown = _render_literal(out).replace("\uff0f", "/")
    assert shown == value


def test_backslash_pipe_is_not_a_separator() -> None:
    for value in ("|", r"\|", r"\\|", "a\\", "a\\|b"):
        out = _inert_text(value)
        assert len(_split_row(f"| {out} |")) == 3, (value, out)
        assert _render_literal(out) == value


def test_truncation_never_splits_an_escape_or_entity() -> None:
    out = _inert_text("[" * 10, limit=5)
    assert out == "\\[" * 5
    out = _inert_text("&" * 10, limit=3)
    assert out == "&amp;" * 3
    out = _inert_text("\\" * 10, limit=4)
    assert out == "\\\\" * 4
    out = _inert_text("a|" * 10, limit=3)
    assert out == "a\\|a"


def test_only_reference_forms_lose_their_hash() -> None:
    for kept in ("Case # of 7", "C# and F#", "#hashtag", "a # b", "##"):
        assert _inert_text(kept) == kept.replace("&", "&amp;"), kept
    for ref in ("see #5", "(#99)", "o/r#12", "GH-4"):
        out = _inert_text(ref)
        assert "#" not in out and "GH-" not in out.upper().replace("GH\uff0d", ""), ref


def test_bidi_and_zero_width_controls_are_stripped() -> None:
    bad = "".join(chr(c) for c in (*range(0x200B, 0x2010), *range(0x202A, 0x202F),
                                   *range(0x2066, 0x206A), 0xFEFF))
    assert _inert_text(f"a{bad}b") == "ab"
    assert _inert_text("a&#x202E;b&#8203;c") == "abc"
