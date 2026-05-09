"""Minimal YAML-frontmatter parser for ``web/src/content/finds/*.mdx``.

Purpose-built (no PyYAML dep) because the finds frontmatter schema is
small and stable. We only read ``title``, ``subtitle``, and ``cards``
— anything else (``tags``, ``summary``, ``published``) can change
without breaking the OG build.

If the schema ever grows beyond what this parser handles cleanly,
swap to PyYAML and add ``pyyaml`` to ``pyproject.toml`` — but that's
not necessary today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class FindsFrontmatter:
    """Structural fields extracted from a ``finds/*.mdx`` frontmatter."""

    slug: str
    title: str
    subtitle: str | None
    cards: tuple[str, ...]


def _strip_yaml_string(value: str) -> str:
    """Strip surrounding single/double quotes if present, return raw text."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _parse_scalar(line: str, key: str) -> str | None:
    """If ``line`` is ``key: value``, return the unquoted value, else None."""
    prefix = f"{key}:"
    if not line.lstrip().startswith(prefix):
        return None
    after = line.split(prefix, 1)[1]
    return _strip_yaml_string(after)


def _parse_card_list(lines: list[str], start: int) -> tuple[list[str], int]:
    """Read a ``cards:`` block list. Returns (ids, next_line_index).

    Handles the only form used in this repo: ``cards:`` followed by
    indented ``  - <hex>`` lines. Stops at the first non-list line.
    """
    cards: list[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].lstrip()
        if not stripped.startswith("- "):
            break
        cards.append(_strip_yaml_string(stripped[2:].strip()))
        i += 1
    return cards, i


def parse_finds_frontmatter(mdx_path: Path) -> FindsFrontmatter:
    """Parse a ``.mdx`` frontmatter block into a :class:`FindsFrontmatter`.

    Reads ``title``, ``subtitle``, and ``cards`` — the only fields the
    OG renderer needs.
    """
    text = mdx_path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"no YAML frontmatter found in {mdx_path}")
    block = match.group(1)
    lines = block.splitlines()

    title: str | None = None
    subtitle: str | None = None
    cards: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("cards:"):
            cards, i = _parse_card_list(lines, i + 1)
            continue
        scalar_title = _parse_scalar(line, "title")
        if scalar_title is not None and title is None:
            title = scalar_title
        scalar_subtitle = _parse_scalar(line, "subtitle")
        if scalar_subtitle is not None and subtitle is None:
            subtitle = scalar_subtitle
        i += 1

    if title is None:
        raise ValueError(f"frontmatter missing 'title' in {mdx_path}")

    return FindsFrontmatter(
        slug=mdx_path.stem,
        title=title,
        subtitle=subtitle if subtitle else None,
        cards=tuple(cards),
    )
