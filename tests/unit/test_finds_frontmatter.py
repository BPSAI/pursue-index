"""Tests for the finds-frontmatter parser.

These tests exist as a parity contract with Astro's content config
(``web/src/content.config.ts``). When the Astro schema grows a field
the OG renderer cares about (today: ``draft``), the Python parser
must understand it the same way — otherwise the two consumers drift
silently and we ship OG cards for entries Astro skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.web.finds_frontmatter import (
    FindsFrontmatter,
    parse_finds_frontmatter,
)


# --- draft field (parity with Astro's z.boolean().default(false)) --------


def test_parse_frontmatter_draft_defaults_false(tmp_path: Path) -> None:
    """Astro: ``draft: z.boolean().default(false)`` — when the key is
    absent, Astro renders the entry; the Python parser must match."""
    mdx = tmp_path / "no-draft-field.mdx"
    mdx.write_text(
        '---\n'
        'title: "Default Draft Test"\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.draft is False


def test_parse_frontmatter_draft_true(tmp_path: Path) -> None:
    """``draft: true`` → Astro filters this entry out; we surface that
    as ``fm.draft is True`` so the build script can skip it too."""
    mdx = tmp_path / "real-draft.mdx"
    mdx.write_text(
        '---\n'
        'title: "WIP Entry"\n'
        'draft: true\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.draft is True


def test_parse_frontmatter_draft_false_explicit(tmp_path: Path) -> None:
    """Explicit ``draft: false`` is identical to absence."""
    mdx = tmp_path / "explicit-false.mdx"
    mdx.write_text(
        '---\n'
        'title: "Published Entry"\n'
        'draft: false\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.draft is False


# --- trailing newline tolerance (P2-8) -----------------------------------


def test_parse_frontmatter_no_trailing_newline(tmp_path: Path) -> None:
    """An ``.mdx`` whose closing ``---`` is the last byte (no trailing
    LF) must still parse — the previous regex required ``\\n`` after
    the closer and would silently fail on hand-edited files."""
    mdx = tmp_path / "no-trailing.mdx"
    mdx.write_text(
        '---\n'
        'title: "No Trailing Newline"\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---'  # NB: no trailing newline, no body
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.title == "No Trailing Newline"
    assert fm.cards == ("aabbccddeeff0011",)


# --- escaped quotes (LOW-001) --------------------------------------------


def test_parse_frontmatter_unescapes_double_quotes(tmp_path: Path) -> None:
    """``"foo\\"bar"`` should yield ``foo"bar`` (the YAML-style escape
    is undone), not ``foo\\"bar`` (backslash retained on the rendered
    PNG). Pillow renders the string opaquely; the lone backslash is
    cosmetically wrong."""
    mdx = tmp_path / "escaped.mdx"
    # In Python source this is a backslash-quote pair embedded in a
    # double-quoted YAML scalar.
    mdx.write_text(
        '---\n'
        'title: "Bell \\"Witnesses\\" — 1947"\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.title == 'Bell "Witnesses" — 1947'


def test_parse_frontmatter_unescapes_single_quotes(tmp_path: Path) -> None:
    """Single-quoted scalars unescape ``\\'`` to ``'`` similarly."""
    mdx = tmp_path / "escaped-single.mdx"
    mdx.write_text(
        "---\n"
        "title: 'O\\'Connor Report'\n"
        "cards:\n"
        "  - aabbccddeeff0011\n"
        "---\n"
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.title == "O'Connor Report"


# --- inline YAML list -----------------------------------------------------


def test_parse_frontmatter_inline_card_list(tmp_path: Path) -> None:
    """Astro accepts ``cards: ["abc", "def"]`` (inline-flow YAML list).
    The block-list path silently dropped these to ``()``; treat the
    inline form as a first-class shape so the source label still picks
    a real card."""
    mdx = tmp_path / "inline-list.mdx"
    mdx.write_text(
        '---\n'
        'title: "Inline Cards"\n'
        'cards: ["aabbccddeeff0011", "1122334455667788"]\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.cards == ("aabbccddeeff0011", "1122334455667788")


def test_parse_frontmatter_inline_empty_list(tmp_path: Path) -> None:
    """``cards: []`` is also valid YAML; treat it as no cards."""
    mdx = tmp_path / "empty-inline.mdx"
    mdx.write_text(
        '---\n'
        'title: "Empty Cards"\n'
        'cards: []\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.cards == ()


# --- ergonomics: dataclass shape stays minimal ---------------------------


def test_finds_frontmatter_dataclass_has_draft_field() -> None:
    """Sanity: the dataclass exposes ``draft`` as a public attribute."""
    fm = FindsFrontmatter(
        slug="x",
        title="x",
        subtitle=None,
        cards=(),
        draft=False,
    )
    assert fm.draft is False
