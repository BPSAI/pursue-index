"""Where a transcript's page numbers are already relied on.

A page number is a citation anchor: ``pages.json`` carries it into search
results, and a find's ``<Cite card=... page=...>`` links to it. Re-paginating a
card moves those anchors, so both places are checked before it is done.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PAGES_JSON = Path("web/public/data/pages.json")
FINDS_DIR = Path("web/src/content/finds")


def citation_anchors(card_id: str, repo_root: Path) -> list[str]:
    """Human-readable places that already reference ``card_id``'s page numbers."""
    found: list[str] = []
    pages_path = repo_root / PAGES_JSON
    if pages_path.exists():
        rows = json.loads(pages_path.read_text(encoding="utf-8"))
        count = sum(1 for row in rows if row.get("card_id") == card_id)
        if count:
            found.append(f"{PAGES_JSON} ({count} pages)")
    cite = re.compile(r"<Cite\b[^>]*\bcard=[\"']" + re.escape(card_id) + r"[\"']")
    for mdx in sorted((repo_root / FINDS_DIR).glob("*.mdx")):
        count = len(cite.findall(mdx.read_text(encoding="utf-8")))
        if count:
            found.append(f"{FINDS_DIR / mdx.name} ({count} citations)")
    return found
