"""Tests for the per-entry OG build script.

These tests pin the contracts the script shares with the Astro
content collection (``web/src/content.config.ts``):

- ``loader: glob({ pattern: "**/*.{md,mdx}", base: "./src/content/finds" })``
  → recursive, both ``.md`` and ``.mdx``. The script must enumerate
  the same set Astro does, otherwise a subdir entry gets a route
  but no OG image.
- ``getCollection("finds", ({ data }) => !data.draft)`` → the script
  must skip ``draft: true`` entries.
- The ``[slug].astro`` source rail uses ``c.id.slice(0, 8)`` — the
  source-label card prefix must match.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_finds_og_images as bfoi  # noqa: E402


# --- Source label: prefix length matches the Astro source rail -----------


def test_source_label_uses_8char_prefix() -> None:
    """``[slug].astro:90`` shows ``c.id.slice(0, 8)`` in the source
    rail. The OG card source label must show the same 8-char prefix
    so the rendered image matches what the page displays."""
    label = bfoi._format_source_label(
        ("0b298cfc9c65a4d6",),
        {"0b298cfc9c65a4d6": {"agency": "NASA"}},
    )
    assert label == "NASA · 0b298cfc"


def test_source_label_falls_back_to_archive() -> None:
    """An unknown card id still gets the 8-char prefix, with the
    ``ARCHIVE`` agency fallback."""
    label = bfoi._format_source_label(("deadbeefcafef00d",), {})
    assert label == "ARCHIVE · deadbeef"


def test_source_label_empty_cards_uses_brand() -> None:
    label = bfoi._format_source_label((), {})
    assert label == "PURSUE://INDEX"


# --- Multi-card label: surface "1 of N" so the picker is testable --------


def test_source_label_multi_card_shows_count() -> None:
    """Entries with multiple cards (``fbi-62-hq-83894-readers-guide.mdx``
    has 10) silently picked card[0] before. Show ``AGENCY · prefix · 1 of N``
    so the source-card disambiguation is visible on the OG card."""
    card_index = {
        "bcf2e688dfbc220d": {"agency": "FBI"},
        "4844321219e306af": {"agency": "FBI"},
    }
    label = bfoi._format_source_label(
        ("bcf2e688dfbc220d", "4844321219e306af"), card_index
    )
    assert label == "FBI · bcf2e688 · 1 of 2"


def test_source_label_single_card_no_count() -> None:
    """Single-card entries (the common case) keep the original
    two-part label — no count noise when there's no choice."""
    label = bfoi._format_source_label(
        ("0b298cfc9c65a4d6",),
        {"0b298cfc9c65a4d6": {"agency": "NASA"}},
    )
    assert "of" not in label
    assert label == "NASA · 0b298cfc"


# --- Recursive glob + .md support: parity with Astro loader --------------


def test_enumerate_entries_picks_up_subdir(tmp_path: Path) -> None:
    """Astro's loader is ``**/*.{md,mdx}`` — recursive. A curator who
    organizes finds under ``foo/bar.mdx`` would get a route at
    ``/finds/foo/bar`` from Astro but no OG image from a non-recursive
    script. The enumerator must mirror Astro."""
    finds = tmp_path / "finds"
    (finds / "sub").mkdir(parents=True)
    flat = finds / "flat-entry.mdx"
    nested = finds / "sub" / "nested-entry.mdx"
    flat.write_text(
        '---\ntitle: "Flat"\ncards:\n  - aabbccddeeff0011\n---\n'
    )
    nested.write_text(
        '---\ntitle: "Nested"\ncards:\n  - aabbccddeeff0011\n---\n'
    )
    paths = bfoi._enumerate_entries(finds)
    rels = sorted(str(p.relative_to(finds)) for p in paths)
    assert "flat-entry.mdx" in rels
    assert "sub/nested-entry.mdx" in rels


def test_enumerate_entries_picks_up_md_extension(tmp_path: Path) -> None:
    """Astro's loader matches both ``.md`` and ``.mdx``. The script
    must too."""
    finds = tmp_path / "finds"
    finds.mkdir()
    md = finds / "plain.md"
    md.write_text('---\ntitle: "Plain"\ncards:\n  - aabbccddeeff0011\n---\n')
    paths = bfoi._enumerate_entries(finds)
    assert any(p.name == "plain.md" for p in paths)


# --- Slug parity: subdir entry id is "subdir/foo", not just "foo" --------


def test_entry_id_for_path_uses_relative_path_stem(tmp_path: Path) -> None:
    """Astro derives ``entry.id`` from the filesystem path relative to
    the content base, without extension. ``foo/bar.mdx`` → ``foo/bar``.
    The OG output filename must match so the URL contract holds."""
    finds = tmp_path / "finds"
    (finds / "sub").mkdir(parents=True)
    nested = finds / "sub" / "nested.mdx"
    nested.write_text("---\ntitle: x\n---\n")
    assert bfoi._entry_id_for_path(nested, finds) == "sub/nested"


def test_entry_id_for_path_flat_drops_extension(tmp_path: Path) -> None:
    finds = tmp_path / "finds"
    finds.mkdir()
    flat = finds / "apollo-17.mdx"
    flat.write_text("---\ntitle: x\n---\n")
    assert bfoi._entry_id_for_path(flat, finds) == "apollo-17"


# --- Draft handling: parity with Astro's getCollection filter ------------


def test_main_skips_draft_entries(tmp_path: Path) -> None:
    """``getCollection("finds", ({ data }) => !data.draft)`` filters
    drafts out of every Astro route. The build script must not write
    PNGs for entries Astro skips, otherwise the smoke test passes
    forward (every mdx → PNG) but ``/og/finds/<draft-slug>.png`` is
    an orphan."""
    finds = tmp_path / "finds"
    finds.mkdir()
    out = tmp_path / "out"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"csv_sha256": "0" * 64, "cards": []})
    )
    (finds / "published.mdx").write_text(
        '---\ntitle: "Published"\ncards:\n  - aabbccddeeff0011\n---\n'
    )
    (finds / "wip.mdx").write_text(
        '---\ntitle: "WIP"\ndraft: true\ncards:\n  - aabbccddeeff0011\n---\n'
    )
    rc = bfoi.main(
        [
            "--finds-dir",
            str(finds),
            "--out-dir",
            str(out),
            "--manifest",
            str(manifest),
        ]
    )
    assert rc == 0
    assert (out / "published.png").exists()
    assert not (out / "wip.png").exists()


# --- Defense-in-depth: refuse path-traversing slugs ----------------------


def test_assert_safe_slug_rejects_traversal() -> None:
    """A contributor file named ``../evil.mdx`` (or symlinked through
    one) would otherwise land a PNG one directory above out_dir.
    Defense-in-depth: explicit assertion before write."""
    with pytest.raises(ValueError):
        bfoi._assert_safe_slug("../evil")
    with pytest.raises(ValueError):
        bfoi._assert_safe_slug("foo/../evil")
    with pytest.raises(ValueError):
        bfoi._assert_safe_slug("c:\\evil")


def test_assert_safe_slug_accepts_normal() -> None:
    """Real slugs (flat or nested) must pass."""
    bfoi._assert_safe_slug("apollo-17")
    bfoi._assert_safe_slug("sub/nested-entry")
