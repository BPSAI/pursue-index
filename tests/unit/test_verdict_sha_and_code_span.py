"""Commit-SHA neutralizing is case-insensitive and cue-aware, and the code-span flag
is only ever used for values the caller wraps in backticks."""

from __future__ import annotations

import re
from pathlib import Path

from pursue_index.scrape import year_normalize_report as report_mod
from pursue_index.scrape.year_normalize import DateReport
from pursue_index.scrape.year_normalize_report import _inert, verdict_date_lines

_FW = {chr(c + 0xFEE0) for c in range(0x21, 0x7F)}


def _defanged(text: str, sha: str) -> bool:
    return sha not in text and text.count(sha[1:]) >= 1 and any(f in text for f in _FW)


def test_uppercase_sha_is_neutralized() -> None:
    assert _defanged(_inert("fix DEADBEEF1234 here"), "DEADBEEF1234")


def test_mixed_case_sha_is_neutralized() -> None:
    assert _defanged(_inert("fix DeadBeef1234 here"), "DeadBeef1234")


def test_all_letter_run_after_commit_cue_is_neutralized() -> None:
    assert _defanged(_inert("commit deadbeefcafe"), "deadbeefcafe")
    assert _defanged(_inert("Commit DEADBEEFCAFE"), "DEADBEEFCAFE")


def test_all_letter_run_after_sha_cue_is_neutralized() -> None:
    assert _defanged(_inert("sha: abcdefabcdef"), "abcdefabcdef")


def test_all_letter_run_after_at_cue_is_neutralized() -> None:
    assert "abcdefabcdef" not in _inert("repo@abcdefabcdef")


def test_plain_all_letter_word_stays_literal() -> None:
    assert _inert("deadbeef in prose") == "deadbeef in prose"
    assert _inert("a decaded facade") == "a decaded facade"


def test_digit_runs_and_years_stay_literal() -> None:
    assert _inert("1234567") == "1234567"
    assert _inert("in 2026 and 12345678901") == "in 2026 and 12345678901"
    assert _inert("commit 1234567") == "commit 1234567"


def _call_sites() -> list[str]:
    src = Path(report_mod.__file__).read_text()
    return re.findall(r"^.*for_code_span=True.*$", src, re.M)


def test_flag_is_renamed_and_old_name_gone() -> None:
    src = Path(report_mod.__file__).read_text()
    assert "for_code_span" in src
    assert not re.search(r"\bcode=(True|False)", src)


def test_every_for_code_span_call_site_is_wrapped_in_backticks() -> None:
    sites = _call_sites()
    assert sites
    for line in sites:
        for m in re.finditer(r"(.)\{_inert\([^{}]*for_code_span=True\)\}(.)", line):
            assert m.group(1) == "`" and m.group(2) == "`", line


def test_rendered_code_span_values_are_wrapped() -> None:
    row = {"card_id": "abc|123", "title": "t", "field": "f", "raw": "a|b&c",
           "reason": "r"}
    out = verdict_date_lines(DateReport(considered=1, unresolved=[row]))
    assert "`abc|123`" in out and "`a|b&c`" in out
