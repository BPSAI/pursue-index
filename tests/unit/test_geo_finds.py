"""`llms-full.txt` inlines every `/finds` article; it must track the `.mdx`.

The `## Finds` section used to be preserved byte-for-byte by the generator,
so a corrected quote in a finds article never reached the LLM-facing text.
These tests pin the MDX-to-text conversion the section was originally built
with (so unchanged articles round-trip byte-identically) and the regeneration
of the whole section from the sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.geo.finds import (
    Find,
    load_finds,
    parse_frontmatter,
    render_finds_index,
    render_finds_section,
    replace_finds_section,
    strip_mdx,
)

_MDX = """---
title: "A 'Quoted' Title"
summary: "One summary line."
tags: ["a", "b"]
cards:
  - 9ed140b9186c20c5
  - ffd9dfd4bceb163f
published: 2026-07-11
---

import Cite from "../../components/Cite.astro";

## Heading

> "a quote" <Cite card="9ed140b9186c20c5" page={1} q="a quote" />
"""


def _write(root: Path, slug: str, text: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{slug}.mdx").write_bytes(text.encode("utf-8"))


class TestFrontmatter:
    def test_scalars_lose_their_outer_quotes_and_lists_collect(self):
        meta, body = parse_frontmatter(_MDX)
        assert meta["title"] == "A 'Quoted' Title"
        assert meta["published"] == "2026-07-11"
        assert meta["cards"] == ["9ed140b9186c20c5", "ffd9dfd4bceb163f"]
        assert meta["tags"] == ["a", "b"]
        assert body.startswith("\nimport Cite")

    def test_escaped_quotes_in_a_double_quoted_scalar_are_unescaped(self):
        # YAML escapes inside "...": the site renders the bare characters, so
        # the LLM-facing text must not carry the backslashes.
        raw = '---\ntitle: "Twenty-Five \\"Cold Orbs\\" and a \\\\ path"\n---\nbody\n'
        meta, _ = parse_frontmatter(raw)
        assert meta["title"] == 'Twenty-Five "Cold Orbs" and a \\ path'

    def test_single_quoted_and_bare_scalars_keep_their_backslashes(self):
        raw = "---\nsummary: 'a \\\" b'\nnote: c \\\" d\n---\n"
        meta, _ = parse_frontmatter(raw)
        assert meta["summary"] == 'a \\" b'
        assert meta["note"] == 'c \\" d'

    def test_no_frontmatter_returns_the_whole_text_as_body(self):
        assert parse_frontmatter("just text\n") == ({}, "just text\n")


class TestStripMdx:
    def test_import_lines_are_dropped_and_cites_become_markers(self):
        out = strip_mdx(_MDX.split("---\n", 2)[2])
        assert "import" not in out
        assert out.endswith('> "a quote" [cite: card 9ed140b9186c20c5 p.1 "a quote"]')
        assert out.startswith("## Heading")

    def test_a_cite_whose_q_holds_an_apostrophe_keeps_its_marker(self):
        out = strip_mdx('x <Cite card="abc" page={2} q="it\'s here" /> y')
        assert out == 'x [cite: card abc p.2 "it\'s here"] y'

    def test_a_single_quoted_q_may_hold_double_quotes(self):
        out = strip_mdx("x <Cite card='abc' page={2} q='the \"T\" shape' /> y")
        assert out == 'x [cite: card abc p.2 "the "T" shape"] y'

    def test_a_labelled_cite_becomes_a_page_marker(self):
        # label is display text, not a quote from the source.
        out = strip_mdx('see <Cite card="abc" page={66} label="the FBI file" /> here')
        assert out == "see [cite: card abc p.66] here"

    def test_attribute_order_does_not_matter(self):
        out = strip_mdx('<Cite q="a b" page={3} card="abc" />')
        assert out == '[cite: card abc p.3 "a b"]'

    def test_a_cite_without_card_or_page_is_stripped(self):
        assert strip_mdx('x <Cite card="abc" /> y') == "x  y"

    def test_bare_component_tags_are_removed(self):
        assert strip_mdx("anchored with `<Cite>` to") == "anchored with `` to"


class TestSection:
    def test_newest_first_with_ties_in_filename_order(self, tmp_path):
        _write(tmp_path, "b-old", _MDX.replace("2026-07-11", "2026-06-01"))
        _write(tmp_path, "c-new", _MDX)
        _write(tmp_path, "a-new", _MDX)
        assert [f.slug for f in load_finds(tmp_path)] == ["a-new", "c-new", "b-old"]

    def test_drafts_are_skipped(self, tmp_path):
        _write(tmp_path, "d", _MDX.replace("published:", "draft: true\npublished:"))
        assert load_finds(tmp_path) == []

    def test_rendered_block_format(self, tmp_path):
        _write(tmp_path, "slug-one", _MDX)
        body = render_finds_section(load_finds(tmp_path))
        assert body == (
            "1 curated reading guides authored from specific cards and pages.\n"
            "\n"
            "### slug-one — A 'Quoted' Title\n"
            "\n"
            "- URL: https://pursueindex.com/finds/slug-one\n"
            "- Published: 2026-07-11\n"
            "- Cards: 9ed140b9186c20c5, ffd9dfd4bceb163f\n"
            "\n"
            "One summary line.\n"
            "\n"
            "## Heading\n"
            "\n"
            '> "a quote" [cite: card 9ed140b9186c20c5 p.1 "a quote"]\n'
        )

    def test_replace_runs_to_the_end_of_the_document(self):
        doc = "# T\n\n## Cards\n\nc\n\n## Finds\n\nold\n\n## Inner heading\n\nold\n"
        out = replace_finds_section(doc, "new body\n")
        assert out == "# T\n\n## Cards\n\nc\n\n## Finds\n\nnew body\n"

    def test_replace_refuses_a_document_without_the_section(self):
        with pytest.raises(ValueError):
            replace_finds_section("# T\n\n## Cards\n\nc\n", "x\n")


class TestIndex:
    def _find(self, summary):
        meta = {"title": "T", "summary": summary} if summary is not None else {"title": "T"}
        return Find(slug="s", meta=meta, body="")

    def test_summary_whitespace_collapses(self):
        out = render_finds_index([self._find("  a\n  b  ")])
        assert out == "- [s — T](https://pursueindex.com/finds/s): a b\n"

    def test_long_summary_is_cut_to_157_chars_and_an_ellipsis(self):
        out = render_finds_index([self._find("x" * 161)])
        assert out.endswith(": " + "x" * 157 + "…\n")

    def test_a_160_char_summary_is_kept_whole(self):
        assert render_finds_index([self._find("x" * 160)]).endswith(": " + "x" * 160 + "\n")

    def test_no_summary_leaves_an_empty_tail(self):
        assert (
            render_finds_index([self._find(None)])
            == "- [s — T](https://pursueindex.com/finds/s): \n"
        )
