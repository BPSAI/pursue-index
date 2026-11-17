"""Render the `## Finds` section of `llms-full.txt` from the `/finds` MDX sources.

The section was first emitted by a JavaScript generator that has since been
retired; after that the Python generator preserved it verbatim, so corrections
to a finds article never reached the LLM-facing text. This module is a faithful
port of that original conversion, quirks included, so an article whose source
has not changed renders byte-for-byte as it is already published:

* frontmatter is read with the original minimal parser (one leading and one
  trailing quote stripped from scalars, no YAML unescaping);
* ``import`` lines are dropped;
* ``<Cite card="…" page={N} q="…" />`` becomes ``[cite: card … p.N "…"]``. The
  attribute pattern excludes both quote characters, so a cite whose ``q``
  contains an apostrophe is not matched and is removed by the generic strip;
* any remaining capitalised JSX tag is removed;
* articles are ordered newest ``published`` first, ties in filename order,
  and ``draft: true`` articles are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pursue_index.geo.llms import SITE_ORIGIN

__all__ = [
    "Find",
    "load_finds",
    "parse_frontmatter",
    "render_finds_section",
    "replace_finds_section",
    "strip_mdx",
]

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_KEY_RE = re.compile(r"^[a-zA-Z_]+:")
_LIST_ITEM_RE = re.compile(r"^\s+-\s+")
_OUTER_QUOTES_RE = re.compile(r"^[\"']|[\"']\Z")

_IMPORT_RE = re.compile(r"^import\s.*$", re.MULTILINE)
_CITE_RE = re.compile(
    r"<Cite\s+card=[\"']([^\"']+)[\"']\s+page=\{?([0-9]+)\}?"
    r"(?:\s+q=[\"']([^\"']*)[\"'])?\s*/>"
)
_SELF_CLOSING_JSX_RE = re.compile(r"<[A-Z][A-Za-z]*\s[^>]*/>")
_JSX_TAG_RE = re.compile(r"</?[A-Z][A-Za-z]*[^>]*>")

_FINDS_HEADING_RE = re.compile(r"^##[ \t]+Finds[ \t]*\n", re.MULTILINE)


@dataclass(frozen=True)
class Find:
    slug: str
    meta: dict
    body: str


def _unquote(value: str) -> str:
    return _OUTER_QUOTES_RE.sub("", value)


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """The original generator's minimal ``---``-delimited frontmatter parser."""
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        return {}, raw
    meta: dict = {}
    current: str | None = None
    for line in re.split(r"\r?\n", match.group(1)):
        if not line.strip():
            continue
        if _KEY_RE.match(line):
            key, _, rest = line.partition(":")
            current, value = key.strip(), rest.strip()
            if value in ("", "[]"):
                meta[current] = [] if value == "[]" else None
            elif value.startswith("[") and value.endswith("]"):
                items = (_unquote(s.strip()) for s in value[1:-1].split(","))
                meta[current] = [s for s in items if s]
            else:
                meta[current] = _unquote(value)
        elif _LIST_ITEM_RE.match(line) and current:
            if not isinstance(meta.get(current), list):
                meta[current] = []
            meta[current].append(_unquote(_LIST_ITEM_RE.sub("", line).strip()))
    return meta, match.group(2)


def _cite_marker(match: re.Match) -> str:
    card, page, quote = match.groups()
    return f"[cite: card {card} p.{page}{f' \"{quote}\"' if quote else ''}]"


def strip_mdx(body: str) -> str:
    """MDX body to plain text, exactly as the original generator rendered it."""
    out = _IMPORT_RE.sub("", body)
    out = _CITE_RE.sub(_cite_marker, out)
    out = _SELF_CLOSING_JSX_RE.sub("", out)
    out = _JSX_TAG_RE.sub("", out)
    return out.strip()


def load_finds(finds_dir: Path) -> list[Find]:
    """Every non-draft ``.md``/``.mdx`` article, newest ``published`` first."""
    finds: list[Find] = []
    for path in sorted(finds_dir.iterdir(), key=lambda p: p.name):
        if path.suffix not in (".md", ".mdx"):
            continue
        # Bytes, not read_text(): universal-newline decoding would rewrite \r\n.
        meta, body = parse_frontmatter(path.read_bytes().decode("utf-8"))
        if meta.get("draft") == "true":
            continue
        finds.append(Find(slug=path.stem, meta=meta, body=body))
    # list.sort is stable, so equal dates keep filename order.
    finds.sort(key=lambda f: str(f.meta.get("published", "undefined")), reverse=True)
    return finds


def _render_find(find: Find) -> list[str]:
    meta = find.meta
    lines = [
        f"### {find.slug} — {meta.get('title')}",
        "",
        f"- URL: {SITE_ORIGIN}/finds/{find.slug}",
        f"- Published: {meta.get('published')}",
    ]
    cards = meta.get("cards")
    if isinstance(cards, list) and cards:
        lines.append(f"- Cards: {', '.join(cards)}")
    if meta.get("summary"):
        lines += ["", meta["summary"]]
    return [*lines, "", strip_mdx(find.body), ""]


def render_finds_section(finds: list[Find]) -> str:
    """The text under the ``## Finds`` heading, through the end of the file."""
    lines = [f"{len(finds)} curated reading guides authored from specific cards and pages.", ""]
    for find in finds:
        lines += _render_find(find)
    return "\n".join(lines)


def replace_finds_section(document: str, body: str) -> str:
    """Replace everything from the ``## Finds`` heading to the end of the file.

    `## Finds` is the final section, and the articles it inlines carry their
    own ``## `` headings, so it cannot be bounded by the next heading the way
    `replace_section` bounds the others.
    """
    match = _FINDS_HEADING_RE.search(document)
    if match is None:
        raise ValueError("section 'Finds' not found — refusing to append blindly")
    return f"{document[: match.end()]}\n{body}"


def sync_finds_section(document: str, finds_dir: Path) -> str:
    """``document`` with its ``## Finds`` section regenerated from ``finds_dir``."""
    return replace_finds_section(document, render_finds_section(load_finds(finds_dir)))
