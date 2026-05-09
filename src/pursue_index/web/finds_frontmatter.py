"""Minimal YAML-frontmatter parser for ``web/src/content/finds/*.mdx``.

Purpose-built (no PyYAML dep) because the finds frontmatter schema is
small and stable. We only read the fields the OG renderer actually
cares about: ``title``, ``subtitle``, ``cards``, and ``draft``. Other
fields (``tags``, ``summary``, ``published``) can change without
breaking the OG build.

If the schema ever grows beyond what this parser handles cleanly,
swap to PyYAML and add ``pyyaml`` to ``pyproject.toml`` — but that's
not necessary today.

Parity contract with ``web/src/content.config.ts``:

- ``title``: required string
- ``subtitle``: optional string
- ``cards``: list of strings (block list ``- foo`` OR inline ``[a, b]``)
- ``draft``: boolean, default false — Astro filters ``draft: true``
  out via ``getCollection("finds", ({ data }) => !data.draft)``, so
  the build script must skip the same set
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Trailing newline after the closing ``---`` is optional: a hand-edited
# .mdx whose last byte is the closer must still parse. The previous
# expression required ``\n`` after the closer and silently failed.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(\n|\Z)", re.DOTALL)
_INLINE_LIST_RE = re.compile(r"^\[(.*)\]$")


@dataclass(frozen=True)
class FindsFrontmatter:
    """Structural fields extracted from a ``finds/*.mdx`` frontmatter."""

    slug: str
    title: str
    subtitle: str | None
    cards: tuple[str, ...]
    draft: bool = False


def _strip_yaml_string(value: str) -> str:
    """Strip surrounding single/double quotes and undo simple escapes.

    The frontmatter renders into a PNG via Pillow, which treats the
    string opaquely. A literal ``\\"`` in the rendered title looks
    cosmetically wrong, so we undo the standard YAML-style escape pass
    after stripping the outer quote pair.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\'", "'")
    return value


def _parse_scalar(line: str, key: str) -> str | None:
    """If ``line`` is ``key: value``, return the unquoted value, else None."""
    prefix = f"{key}:"
    if not line.lstrip().startswith(prefix):
        return None
    after = line.split(prefix, 1)[1]
    return _strip_yaml_string(after)


def _parse_inline_list(value: str) -> list[str] | None:
    """Parse an inline YAML flow list ``[a, b, "c"]`` to a list.

    Returns ``None`` if ``value`` is not in flow-list form, so callers
    can fall through to the block-list path.
    """
    value = value.strip()
    match = _INLINE_LIST_RE.match(value)
    if not match:
        return None
    body = match.group(1).strip()
    if not body:
        return []
    return [_strip_yaml_string(item) for item in body.split(",")]


def _parse_card_list(lines: list[str], start: int) -> tuple[list[str], int]:
    """Read a ``cards:`` block list. Returns (ids, next_line_index).

    Handles indented ``- <hex>`` lines; stops at the first non-list
    line. The inline-flow form ``cards: [a, b]`` is handled by the
    caller before this is invoked.
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


def _parse_bool(value: str) -> bool:
    """Tolerant boolean parser: ``true``/``yes``/``1`` → True, else False.

    Astro's zod parses ``draft: true`` (lowercase) — that's the only
    shape we expect to see, but the broader rule keeps a typo
    (``True``, ``yes``) from silently flipping the answer to False.
    """
    return value.strip().lower() in {"true", "yes", "1"}


def _read_cards_field(lines: list[str], i: int) -> tuple[list[str], int]:
    """Branch between inline-flow and block-list ``cards:`` shapes."""
    line = lines[i]
    after_key = line.split("cards:", 1)[1].strip()
    inline = _parse_inline_list(after_key) if after_key else None
    if inline is not None:
        return inline, i + 1
    return _parse_card_list(lines, i + 1)


def parse_finds_frontmatter(mdx_path: Path) -> FindsFrontmatter:
    """Parse a ``.mdx`` frontmatter block into a :class:`FindsFrontmatter`.

    Reads ``title``, ``subtitle``, ``cards``, and ``draft`` — the
    fields the OG renderer needs. ``draft`` defaults to False to
    match Astro's ``z.boolean().default(false)``.
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
    draft = False

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("cards:"):
            cards, i = _read_cards_field(lines, i)
            continue
        scalar_title = _parse_scalar(line, "title")
        if scalar_title is not None and title is None:
            title = scalar_title
        scalar_subtitle = _parse_scalar(line, "subtitle")
        if scalar_subtitle is not None and subtitle is None:
            subtitle = scalar_subtitle
        scalar_draft = _parse_scalar(line, "draft")
        if scalar_draft is not None:
            draft = _parse_bool(scalar_draft)
        i += 1

    if title is None:
        raise ValueError(f"frontmatter missing 'title' in {mdx_path}")

    return FindsFrontmatter(
        slug=mdx_path.stem,
        title=title,
        subtitle=subtitle if subtitle else None,
        cards=tuple(cards),
        draft=draft,
    )
