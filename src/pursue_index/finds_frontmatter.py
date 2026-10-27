"""Shared `---`-delimited frontmatter parsing for `/finds` `.mdx` entries.

Dependency-free so both `finds_validator` (single-entry structural
check) and `finds_overlap` (cross-entry overlap gate) can import it
without creating a cycle between them.
"""

from __future__ import annotations

import re

_FRONTMATTER_DELIMITER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def extract_frontmatter(text: str) -> str | None:
    """Return the frontmatter block text (between --- delimiters) or None."""
    m = _FRONTMATTER_DELIMITER.match(text)
    if not m:
        return None
    return m.group(1)


def body_text(text: str) -> str:
    """Return the body — everything after the frontmatter, or the whole
    text if no frontmatter delimiter."""
    m = _FRONTMATTER_DELIMITER.match(text)
    if not m:
        return text
    return text[m.end():]
