"""Unit tests for pursue_index.finds_validator.

The validator is the structural-AC gate the autonomous-finds-pipeline
plan calls "structural validation" — frontmatter completeness, citation
density, methodology block presence. It runs on every PR touching
web/src/content/finds/** (whether human-written or bot-opened) and
catches the obvious failure modes before editorial review.

It does NOT enforce voice, style, or novelty — those are the writer
agent's job and the pipeline's pre-filter job, respectively. The
validator is the bottom-of-the-stack baseline that any draft must pass.
"""

from __future__ import annotations

import pytest

from pursue_index.finds_validator import validate_finds_entry


_VALID_FRONTMATTER = """---
title: "Sample Entry"
subtitle: "A short subtitle"
summary: "A summary sentence longer than ten characters that explains the entry."
tags: ["fbi", "1947"]
cards:
  - bcf2e688dfbc220d
  - b246c782b16be168
published: 2026-05-12
updated: 2026-05-12
---
"""

_VALID_BODY = """
import Cite from "../../components/Cite.astro";

## What the document is

Body content here. <Cite card="bcf2e688dfbc220d" page={70} q="purporting" />

More content. <Cite card="b246c782b16be168" page={68} q="hexagonal" />

## Why this card is in this archive

Closing methodology paragraph. <Cite card="bcf2e688dfbc220d" page={70} q="conducted" />
"""


def _valid_entry(body_extra: str = "") -> str:
    return _VALID_FRONTMATTER + _VALID_BODY + body_extra


# --- Smoke + happy path ---


def test_valid_entry_passes() -> None:
    result = validate_finds_entry(_valid_entry())
    assert result["ok"], f"valid entry failed: {result['errors']}"
    assert result["errors"] == []


# --- Frontmatter completeness ---


def test_missing_frontmatter_fails() -> None:
    result = validate_finds_entry("no frontmatter here\n## body\n<Cite card='abc' />\n")
    assert not result["ok"]
    assert any("frontmatter" in e.lower() for e in result["errors"])


def test_missing_required_field_fails() -> None:
    # Drop `cards:` — every entry must declare which cards it cites
    bad = _VALID_FRONTMATTER.replace(
        "cards:\n  - bcf2e688dfbc220d\n  - b246c782b16be168\n",
        "",
    ) + _VALID_BODY
    result = validate_finds_entry(bad)
    assert not result["ok"]
    assert any("cards" in e.lower() for e in result["errors"])


def test_missing_title_fails() -> None:
    bad = _VALID_FRONTMATTER.replace(
        'title: "Sample Entry"\n',
        "",
    ) + _VALID_BODY
    result = validate_finds_entry(bad)
    assert not result["ok"]
    assert any("title" in e.lower() for e in result["errors"])


def test_missing_summary_fails() -> None:
    bad = _VALID_FRONTMATTER.replace(
        'summary: "A summary sentence longer than ten characters that explains the entry."\n',
        "",
    ) + _VALID_BODY
    result = validate_finds_entry(bad)
    assert not result["ok"]
    assert any("summary" in e.lower() for e in result["errors"])


# --- Citation density (≥3 verbatim citations) ---


def test_too_few_citations_fails() -> None:
    # Two citations only, not three
    body_with_two = """
import Cite from "../../components/Cite.astro";

## What the document is

<Cite card="bcf2e688dfbc220d" page={70} q="x" />

<Cite card="b246c782b16be168" page={68} q="y" />

## Why this card is in this archive

Closing paragraph.
"""
    result = validate_finds_entry(_VALID_FRONTMATTER + body_with_two)
    assert not result["ok"]
    assert any("cite" in e.lower() or "citation" in e.lower() for e in result["errors"])


def test_three_citations_passes() -> None:
    result = validate_finds_entry(_valid_entry())
    assert result["ok"]
    # And we count them
    assert result["stats"]["citation_count"] >= 3


def test_citation_count_excludes_import_line() -> None:
    """`import Cite from "..."` mentions Cite but is not a citation."""
    result = validate_finds_entry(_valid_entry())
    # Three actual <Cite ...> tags in _VALID_BODY
    assert result["stats"]["citation_count"] == 3


# --- Methodology / abstention block present ---


def test_no_methodology_section_fails() -> None:
    body_no_methodology = """
import Cite from "../../components/Cite.astro";

## Just the surface

Some prose. <Cite card="x" page={1} q="a" /> <Cite card="x" page={1} q="b" /> <Cite card="x" page={1} q="c" />
"""
    result = validate_finds_entry(_VALID_FRONTMATTER + body_no_methodology)
    assert not result["ok"]
    assert any(
        "methodology" in e.lower() or "provenance" in e.lower() or "abstention" in e.lower()
        for e in result["errors"]
    )


def test_provenance_section_satisfies_methodology() -> None:
    body = """
import Cite from "../../components/Cite.astro";

## Surface
Body. <Cite card="x" page={1} q="a" /> <Cite card="x" page={1} q="b" /> <Cite card="x" page={1} q="c" />

## Provenance of this entry
Closing methodology paragraph.
"""
    result = validate_finds_entry(_VALID_FRONTMATTER + body)
    assert result["ok"], result["errors"]


def test_why_in_archive_section_satisfies_methodology() -> None:
    """Existing entries use varied wording — 'Why X is in this archive',
    'What the file establishes', etc. All are valid methodology blocks."""
    body = """
import Cite from "../../components/Cite.astro";

## Surface
Body. <Cite card="x" page={1} q="a" /> <Cite card="x" page={1} q="b" /> <Cite card="x" page={1} q="c" />

## Why this card is in this archive
Closing paragraph.
"""
    result = validate_finds_entry(_VALID_FRONTMATTER + body)
    assert result["ok"], result["errors"]


def test_what_we_are_not_claiming_satisfies_methodology() -> None:
    """`What we're not claiming` is the explicit-limits flavor of the
    abstention block."""
    body = """
import Cite from "../../components/Cite.astro";

## Surface
Body. <Cite card="x" page={1} q="a" /> <Cite card="x" page={1} q="b" /> <Cite card="x" page={1} q="c" />

## What we're not claiming
We are not claiming X.
"""
    result = validate_finds_entry(_VALID_FRONTMATTER + body)
    assert result["ok"], result["errors"]


# --- Soft warnings (word count) ---


def test_too_short_body_warns_but_does_not_fail() -> None:
    """Operator flexibility: very short entries may be valid (e.g. a
    minimalist primary-source pin). Warn but don't fail."""
    result = validate_finds_entry(_valid_entry())
    # _VALID_BODY is short — well under the 800-word soft minimum
    assert result["ok"], result["errors"]
    assert any("word" in w.lower() for w in result["warnings"])


# --- Stats output ---


def test_stats_includes_word_count_and_citation_count() -> None:
    result = validate_finds_entry(_valid_entry())
    assert "word_count" in result["stats"]
    assert "citation_count" in result["stats"]
    assert "h2_section_count" in result["stats"]
    assert result["stats"]["word_count"] > 0


# --- Integration: every committed finds entry passes the gate ---


def test_every_committed_finds_entry_validates() -> None:
    """The validator must not fail on entries that are already merged
    and live on the public site. If this fails, the validator rule is
    too strict for current practice; relax it (or fix the entry)."""
    from pathlib import Path

    finds_dir = Path(__file__).resolve().parents[2] / "web" / "src" / "content" / "finds"
    if not finds_dir.is_dir():
        pytest.skip("finds dir not present")

    failed: list[tuple[str, list[str]]] = []
    for path in sorted(finds_dir.glob("*.mdx")):
        result = validate_finds_entry(path.read_text())
        if not result["ok"]:
            failed.append((path.name, result["errors"]))

    if failed:
        msgs = "\n".join(f"  {n}: {errs}" for n, errs in failed[:10])
        pytest.fail(f"{len(failed)} merged entry/entries fail validation:\n{msgs}")
