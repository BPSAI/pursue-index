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

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
import re
from collections import defaultdict

from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from pursue_index.release.chunked_asset import asset_exists, read_asset_json

# Files to grep. Restricted to prose-bearing surfaces so we don't
# false-positive on legitimate references (e.g., committed CSV bytes
# that happen to contain "158 cards" in some row).
TARGET_FILES = [
    "README.md",
    ".paircoder/context/project.md",
    "docs/runbooks/ship-tranche.md",
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
    if asset_exists(pages_path):
        page_count = len(read_asset_json(pages_path))
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
    (
        r"\.paircoder/plans/tranche-diff",
        "old tranche-diff path — should be data/tranche-diffs/",
    ),
    (
        r"git\s+push\s+origin\s+main",
        "git push origin main instruction in runbook",
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


# A hit is a warning, not a stale usage, when a negation precedes it on the
# same line ("do NOT use `git push origin main`", "instead of ...").
_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|instead\s+of|avoid|must\s+not)\b",
    re.IGNORECASE,
)


# The negation must sit right before the command: at most a few filler words
# ("use", "run", "the", ...) and an optional opening quote/backtick between.
_NEAR_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don't|never|instead\s+of|avoid|must\s+not)\W{0,3}"
    r"(?:(?:use|run|using|running|the|a|an|to|of)\s+){0,3}[`\"']?$",
    re.IGNORECASE,
)


def _is_negated_mention(line: str, pattern: str) -> bool:
    """True when every match of `pattern` is directly negated, or sits in an
    inline code span on a line that carries a negation."""
    matches = list(re.finditer(pattern, line, re.IGNORECASE))
    if not matches:
        return False
    has_negation = bool(_NEGATION_RE.search(line))
    for m in matches:
        prefix = line[: m.start()]
        if _NEAR_NEGATION_RE.search(prefix):
            continue
        if has_negation and prefix.count("`") % 2 == 1:  # inside an inline code span
            continue
        return False
    return True


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
            if _is_negated_mention(line, pat):
                continue
            # Check historical-context forgiveness on this + 2 lines above
            # AND 2 lines below (multi-line prose context is common in mdx).
            window = lines[max(0, i - 2): min(len(lines), i + 3)]
            joined = "\n".join(window).lower()
            if any(m in joined for m in _HISTORICAL_CONTEXT_MARKERS):
                continue
            hits.append((i + 1, label, line.strip()))

    # Additional check: unchained clean-qc run/publish (for runbooks only)
    if "ship-tranche" in path.name.lower():
        hits.extend(_check_unchained_clean_qc(lines))

    return hits


def _check_unchained_clean_qc(lines: list[str]) -> list[tuple[int, str, str]]:
    """Check for unchained curate clean-qc run and publish commands.

    Returns hits for cases where run and publish are not properly chained
    with && to ensure publish never follows a failed run.
    """
    hits: list[tuple[int, str, str]] = []
    # Look for clean-qc run commands
    for i, line in enumerate(lines):
        if "clean-qc run" in line and "curate" in line:
            # Check if the next non-empty line has && or if there's a && on this line
            # that leads to publish
            found_chain = False

            # Check if && is on the same line
            if "&&" in line:
                # Check if publish is nearby
                window = "\n".join(lines[i:min(i+5, len(lines))])
                if "publish" in window:
                    found_chain = True
            else:
                # Check the next few lines for && and publish
                for j in range(i + 1, min(i + 5, len(lines))):
                    if "&&" in lines[j] and "publish" in lines[j]:
                        found_chain = True
                        break

            if not found_chain:
                # Check if publish appears within the next 3 lines without chaining
                for j in range(i + 1, min(i + 4, len(lines))):
                    if "clean-qc" in lines[j] and "publish" in lines[j]:
                        # This is a hit only if there's no && between run and publish
                        between_text = "\n".join(lines[i:j+1])
                        if "&&" not in between_text:
                            hits.append((i + 1, "unchained clean-qc run/publish", line.strip()))
                        break

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
