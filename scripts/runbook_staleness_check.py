"""Phase 4 staleness grep — catch hardcoded counts / lists / URLs that
contradict the current manifest state.

Runs grep patterns against the prose surfaces (README, project.md,
finds entries, Astro pages) and flags hits. Designed to be:

- Fast (<1 sec)
- Exit 1 on any hit (pre-commit hook friendly)
- Reports `path:line:excerpt` for each hit so the operator can fix
  with one keystroke

Codifies the staleness grep from `pursue-opsec-staging/runbooks/
site-release-checklist.md` Phase 4.

Usage::

    python scripts/runbook_staleness_check.py
    python scripts/runbook_staleness_check.py --fix-suggest   # show
                                                                fixes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Files to grep. Restricted to prose-bearing surfaces so we don't
# false-positive on legitimate references (e.g., committed CSV bytes
# that happen to contain "158 cards" in some row).
TARGET_FILES = [
    "README.md",
    ".paircoder/context/project.md",
    "web/src/pages/*.astro",
    "web/src/components/*.astro",
    "web/src/components/*.tsx",
    "web/src/content/finds/*.mdx",
]
# Files explicitly EXCLUDED: web/src/lib/release.ts is the source-of-truth
# constants module; its comments legitimately reference historical
# hardcoded values to explain why the dynamic computation exists. Its
# fallback constants (the literal 4161 / 158) are deliberate
# "if-file-missing-on-first-clone" values, not stale claims.


def _load_ground_truth() -> dict:
    """Pull current corpus state from the manifest. Numbers in prose
    that contradict these are stale."""
    m = json.loads((_REPO_ROOT / "data" / "manifests" / "latest.json").read_text())
    pages_path = _REPO_ROOT / "web" / "public" / "data" / "pages.json"
    page_count = 0
    if pages_path.exists():
        page_count = len(json.loads(pages_path.read_text()))
    agencies = sorted({c["agency"] for c in m["cards"] if c.get("agency")})
    return {
        "card_count": len(m["cards"]),
        "page_count": page_count,
        "agency_count": len(agencies),
        "agencies": agencies,
        "csv_sha": m.get("csv_sha256", "")[:16],
        "csv_url": m.get("source_url", ""),
    }


# Patterns to flag. Each pattern is `(regex, why, suggested_fix_template)`.
# Patterns are ALLOWED if the prose explicitly contextualizes them as
# historical (e.g., "rotated from uap-csv.csv"); those exceptions need
# the `_HISTORICAL_CONTEXT_MARKERS` substring on the same or adjacent
# line. Keep the gate strict — false positives are cheaper than false
# negatives.
_PATTERNS = [
    (
        r"\b(116|158|159|160|161|162|163|164)\s+(card|PDF|cards|PDFs)",
        "hardcoded card count",
    ),
    (
        r"\b4,?(?:153|161|111)\b",
        "stale page count",
    ),
    (
        r"\b(four|three)\s+agenc",
        "stale agency count",
    ),
    (
        r"\b(3|4)\s+agencies\b",
        "stale agency count",
    ),
    (
        r"uap-csv\.csv|uap-release001\.csv",
        "stale CSV URL — should be uap-data.csv (or note rotation history explicitly)",
    ),
    (
        r"\bRelease\s+01\s+only\b",
        "stale 'Release 01 only' claim — tranche-2 has landed",
    ),
]

# A pattern hit is FORGIVEN if any of these markers appears on the same
# line or within 2 lines above/below. They signal "this is a historical /
# rotation reference, not a current claim."
_HISTORICAL_CONTEXT_MARKERS = (
    "rotated",       # "rotated from", "rotated twice", "rotation history"
    "renamed",
    "previously",
    "historical",
    "earlier release",
    "rotation",
    "rotated to",
    "moved from",
    "earlier filename",
    "earlier name",
    "legacy",
    "v1.0",          # v1.0 launch numbers (historical baseline)
    "v1.1",
    "launch",        # "at launch", "v1.0 launch baseline"
    "original 4,",   # "original 4,161-page corpus" — explicit historical
    "baseline",      # "v1.0 launch baseline"
    "at the time",
)


def _gather_files() -> list[Path]:
    """Expand the TARGET_FILES patterns to a flat list of existing paths."""
    out: list[Path] = []
    for pat in TARGET_FILES:
        for p in _REPO_ROOT.glob(pat):
            if p.is_file():
                out.append(p)
    return out


def _check_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_number, pattern_label, excerpt) for each stale hit."""
    hits: list[tuple[int, str, str]] = []
    try:
        lines = path.read_text().splitlines()
    except (UnicodeDecodeError, OSError):
        return hits
    for i, line in enumerate(lines):
        for pat, label in _PATTERNS:
            if not re.search(pat, line, re.IGNORECASE):
                continue
            # Check historical-context forgiveness on this + 2 lines above
            # AND 2 lines below (multi-line prose context is common in mdx).
            window = lines[max(0, i - 2): min(len(lines), i + 3)]
            joined = "\n".join(window).lower()
            if any(m in joined for m in _HISTORICAL_CONTEXT_MARKERS):
                continue
            hits.append((i + 1, label, line.strip()))
    return hits


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fix-suggest", action="store_true",
                   help="Also print the current-state value for each "
                        "stale hit so the operator can replace.")
    args = p.parse_args(argv)

    truth = _load_ground_truth()
    files = _gather_files()
    all_hits: dict[Path, list[tuple[int, str, str]]] = defaultdict(list)
    for f in files:
        hits = _check_file(f)
        if hits:
            all_hits[f] = hits

    if not all_hits:
        print(f"staleness: clean (no drift detected against current manifest "
              f"state: {truth['card_count']} cards, {truth['page_count']} pages, "
              f"{truth['agency_count']} agencies)")
        return 0

    print(f"staleness: {sum(len(v) for v in all_hits.values())} hit(s) across "
          f"{len(all_hits)} file(s)")
    print(f"  current state: {truth['card_count']} cards, "
          f"{truth['page_count']} pages, {truth['agency_count']} agencies")
    print()
    for path, hits in sorted(all_hits.items()):
        rel = path.relative_to(_REPO_ROOT)
        for lineno, label, excerpt in hits:
            print(f"  {rel}:{lineno}  [{label}]")
            print(f"    {excerpt[:200]}")
    if args.fix_suggest:
        print()
        print("Current state for replacements:")
        print(f"  card_count: {truth['card_count']}")
        print(f"  page_count: {truth['page_count']}")
        print(f"  agency_count: {truth['agency_count']}")
        print(f"  agencies: {', '.join(truth['agencies'])}")
        print(f"  csv_url: {truth['csv_url']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
