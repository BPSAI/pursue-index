"""Structural validator for `/finds` `.mdx` entries.

Bottom-of-the-stack baseline gate that any entry — hand-written or
bot-opened from the autonomous-finds-pipeline — must pass before
editorial review. The validator does NOT enforce voice, style, or
novelty; those are upstream concerns (writer-agent contract + pipeline
pre-filter). What it DOES enforce is the structural minimum:

1. Frontmatter is present and complete (title, summary, tags, cards,
   published — the fields every entry needs to render correctly and to
   be cited by ID).
2. Citation density meets the editorial bar (≥3 `<Cite ...>` calls —
   the "verbatim citation" rule from the autonomous-finds-pipeline
   plan).
3. The entry contains an abstention / methodology / limits / provenance
   block (the closing editorial frame that prevents "just a wall of
   citations with no editorial framing"). Detected by section-heading
   pattern match against the wording used in the corpus today
   (Provenance, "Why X is in this archive", "What X does not say",
   "What we're not claiming", etc.).

The result is a dict with three top-level keys:

  ok        : bool                  — pass/fail
  errors    : list[str]             — what failed (drives the gate decision)
  warnings  : list[str]             — soft signals (don't gate; surface to operator)
  stats     : dict[str, int]        — word_count, citation_count, h2_section_count

Used in two places:

  * The CI `release-gate.yml` workflow runs this on every PR touching
    `web/src/content/finds/**`.
  * The autonomous-finds-pipeline (private) imports it via
    `from pursue_index.finds_validator import validate_finds_entry` and
    runs it before opening a PR. A draft that fails locally is never
    pushed.

Hand-rolled parser — no PyYAML dep so this can run in lean CI matrices
with just `pip install pytest`. The frontmatter format is YAML-shaped
but constrained enough that a regex-based extractor suffices.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Required frontmatter fields. Per the plan's "frontmatter complete" rule
# and the conventions established by the 21 entries committed as of
# 2026-05-15. `updated` is treated as optional because not every entry
# has been updated post-publish.
_REQUIRED_FRONTMATTER_FIELDS = (
    "title",
    "summary",
    "tags",
    "cards",
    "published",
)

# Minimum verbatim-citation count per the autonomous-finds-pipeline plan.
_MIN_CITATIONS = 3

# Soft word-count band for warnings. Existing entries span 1600-2900
# words; we set the warning floor generously low (800) to allow
# minimalist primary-source pins (e.g. a single-document teletype
# annotation) and the warning ceiling generously high (5000) to allow
# multi-document reader's-guides. Outside this band → warning, not
# error. Operator can override per-entry.
_WORD_COUNT_SOFT_MIN = 800
_WORD_COUNT_SOFT_MAX = 5000

# Methodology / abstention section heading patterns. The existing
# corpus uses varied wording for the closing editorial frame:
#   - "Provenance of this entry"  (6 entries)
#   - "Why X is in (this | the) archive | corpus"  (~6 entries)
#   - "Why it's in the corpus"  (muroc-1947)
#   - "What the file establishes" / "doesn't establish"
#   - "What the file is, and what it isn't"  (62-hq readers guide)
#   - "What we're not claiming"
#   - "What the document does not say"
#   - "What this means for citing the corpus"
#   - "What to read instead"
# Two layers:
#   1. Explicit framing keywords (provenance, methodology, limits, etc.)
#      anywhere in the heading
#   2. Headings starting with "Why" or "What" that include a corpus/
#      archive/limits-shape word later in the heading
# The pattern accepts all of these without false-positiving on a
# generic "## What the document is" surface description (which has
# none of the methodology keywords in any of the right positions).
_METHODOLOGY_HEADING_PATTERN = re.compile(
    r"^##\s+(?:"
    # Layer 1 — explicit framing keywords
    r".*?\b(?:provenance|methodology|caveats?|disclaim\w*|preserv\w+)\b"
    r"|"
    # Layer 2 — "Why X (in | in the) (archive|corpus|file|case|record)"
    r"why\b.*?\b(?:archive|corpus|file|case|record|entry|surface)s?\b"
    r"|"
    # Layer 3 — "What ... (not | doesn't | isn't | don't | aren't | n't)"
    # — the explicit-limits abstention shape
    r"what\b.*?\b(?:not|don't|doesn't|isn't|aren't|n't|never)\b"
    r"|"
    # Layer 4 — "What ... (establish | establishes)" — what the
    # document does or doesn't establish
    r"what\b.*?\b(?:establish\w*|prove\w*|claim\w*)\b"
    r"|"
    # Layer 5 — "What ... (means | mean for) ..." — methodology framing
    r"what\b.*?\b(?:means?|implicat\w+)\b"
    r"|"
    # Layer 6 — "What to read" (e.g. "What to read instead" — pointers
    # to additional context, an abstention by redirection)
    r"what\s+to\s+read"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_FRONTMATTER_DELIMITER = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL
)
_CITE_TAG = re.compile(r"<Cite\s+card=", re.IGNORECASE)
_FRONTMATTER_FIELD = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:", re.MULTILINE)
_H2_HEADING = re.compile(r"^##\s+\S", re.MULTILINE)


def _extract_frontmatter(text: str) -> str | None:
    """Return the frontmatter block text (between --- delimiters) or None."""
    m = _FRONTMATTER_DELIMITER.match(text)
    if not m:
        return None
    return m.group(1)


def _frontmatter_fields(fm_text: str) -> set[str]:
    """Top-level field names present in the frontmatter block.

    A 'top-level' field is a key at column 0 (not indented under a
    parent), regardless of value shape (scalar, list, etc.).
    """
    found: set[str] = set()
    for line in fm_text.splitlines():
        # Skip continuation lines (any leading whitespace)
        if line and not line[0].isspace():
            m = _FRONTMATTER_FIELD.match(line)
            if m:
                found.add(m.group(1))
    return found


def _body_text(text: str) -> str:
    """Return the body — everything after the frontmatter, or the whole
    text if no frontmatter delimiter."""
    m = _FRONTMATTER_DELIMITER.match(text)
    if not m:
        return text
    return text[m.end():]


def _word_count(body: str) -> int:
    """Naive whitespace-token count over the body. Includes the import
    line and section headings — close enough for the soft band check."""
    return len(body.split())


def _citation_count(body: str) -> int:
    return len(_CITE_TAG.findall(body))


def _h2_section_count(body: str) -> int:
    return len(_H2_HEADING.findall(body))


def _has_methodology_block(body: str) -> bool:
    return bool(_METHODOLOGY_HEADING_PATTERN.search(body))


def validate_finds_entry(text: str) -> dict[str, Any]:
    """Validate a single `.mdx` finds entry against the structural AC.

    Returns a dict with ``ok``, ``errors``, ``warnings``, ``stats``.
    See module docstring for field semantics.
    """
    errors: list[str] = []
    warnings: list[str] = []

    fm_text = _extract_frontmatter(text)
    if fm_text is None:
        errors.append("missing frontmatter block (expected `---` delimiters at top)")
        body = text
    else:
        present = _frontmatter_fields(fm_text)
        missing = [f for f in _REQUIRED_FRONTMATTER_FIELDS if f not in present]
        for field in missing:
            errors.append(f"frontmatter: required field `{field}` is missing")
        body = _body_text(text)

    cite_count = _citation_count(body)
    if cite_count < _MIN_CITATIONS:
        errors.append(
            f"too few verbatim citations: found {cite_count} `<Cite>` tag(s), "
            f"need at least {_MIN_CITATIONS}"
        )

    if not _has_methodology_block(body):
        errors.append(
            "missing methodology / abstention / provenance section. "
            "Add a `## Provenance of this entry`, `## Why this card is in this archive`, "
            "`## What we're not claiming`, or similar closing editorial frame."
        )

    words = _word_count(body)
    if words < _WORD_COUNT_SOFT_MIN:
        warnings.append(
            f"word count {words} is below the soft minimum {_WORD_COUNT_SOFT_MIN}; "
            "entry may be too sparse for an editorial frame"
        )
    elif words > _WORD_COUNT_SOFT_MAX:
        warnings.append(
            f"word count {words} is above the soft maximum {_WORD_COUNT_SOFT_MAX}; "
            "consider splitting into multiple entries"
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "word_count": words,
            "citation_count": cite_count,
            "h2_section_count": _h2_section_count(body),
        },
    }


def _format_report(path: Path, result: dict[str, Any]) -> str:
    lines = [f"{path}: {'PASS' if result['ok'] else 'FAIL'}"]
    s = result["stats"]
    lines.append(
        f"  stats: word_count={s['word_count']} "
        f"citation_count={s['citation_count']} "
        f"h2_section_count={s['h2_section_count']}"
    )
    for e in result["errors"]:
        lines.append(f"  ERROR: {e}")
    for w in result["warnings"]:
        lines.append(f"  WARN: {w}")
    return "\n".join(lines)


def main() -> int:
    """CLI entry: `python -m pursue_index.finds_validator <path...>`.

    Exits 0 if every path passes; exits 1 if any path fails.
    With no args, validates every `.mdx` in `web/src/content/finds/`.
    """
    import sys

    if len(sys.argv) > 1:
        paths = [Path(a) for a in sys.argv[1:]]
    else:
        repo_root = Path(__file__).resolve().parents[2]
        paths = sorted((repo_root / "web" / "src" / "content" / "finds").glob("*.mdx"))

    any_failed = False
    for p in paths:
        result = validate_finds_entry(p.read_text())
        print(_format_report(p, result))
        if not result["ok"]:
            any_failed = True
    return 1 if any_failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
