#!/usr/bin/env python3
"""Print raw + cleaned text for one page of one card, side-by-side in stdout.

Usage:
    .venv/bin/python scripts/spotcheck_view.py <card_id> <page>
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pathlib
import textwrap

from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from pursue_index.config import settings
from pursue_index.page_rows import read_latest_pages

# Tracks PURSUE_DATA_ROOT rather than baking in one operator's mount point.
ROOT = settings.ocr_dir


def find_row(path: pathlib.Path, page: int) -> dict | None:
    """The newest row for ``page`` (the sidecar is append-only)."""
    for row in read_latest_pages(path):
        # read_latest_pages already drops rows whose page is missing or not a
        # number; this keeps find_row safe even if handed rows from elsewhere.
        raw = row.get("page")
        if isinstance(raw, bool):
            continue
        try:
            row_page = int(raw)
        except (TypeError, ValueError):
            continue
        if row_page == page:
            return row
    return None


def _parse_args(args: list[str]) -> tuple[str, int] | None:
    """``(card_id, page)``, or None after printing a usage or page error."""
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return None
    try:
        page = int(args[1])
    except ValueError:
        page = 0
    if page < 1:
        print(f"error: page must be a positive integer, got {args[1]!r}", file=sys.stderr)
        return None
    return args[0], page


def _print_cleaned(clean: dict, raw_text: str, wrap) -> None:
    skipped_reason = clean.get("cleanup_skipped")
    cleaned_text = clean.get("text_cleaned") or ""
    print("CLEANED:")
    print("-" * 92)
    if skipped_reason:
        print(f"  [SKIP ROW — reason: {skipped_reason}]")
        print(f"  cleaned text length: {len(cleaned_text)}")
    else:
        ratio = len(cleaned_text) / max(len(raw_text), 1)
        passthrough = clean.get("input_sha256") == clean.get("output_sha256")
        tag = "  [PASS-THROUGH: output identical to raw]" if passthrough else ""
        print(f"  ({len(cleaned_text)} chars, ratio={ratio:.2f}){tag}")
        print(wrap(cleaned_text))
    print()


def main() -> int:
    parsed = _parse_args(sys.argv[1:])
    if parsed is None:
        return 2
    card, page = parsed
    card_dir = ROOT / card
    if not card_dir.exists():
        print(f"error: card dir not found: {card_dir}", file=sys.stderr)
        return 1
    raw = find_row(card_dir / "pages.jsonl", page)
    clean = find_row(card_dir / "pages_cleaned.jsonl", page)
    if raw is None:
        print(f"error: raw page {page} not found in {card}", file=sys.stderr)
        return 1
    raw_text = raw.get("text", "")

    def wrap(text: str) -> str:
        return "\n".join(textwrap.fill(line, width=88) for line in text.splitlines())

    print("=" * 92)
    print(f"CARD {card}  PAGE {page}")
    print("=" * 92)
    print(f"RAW  ({len(raw_text)} chars):")
    print("-" * 92)
    print(wrap(raw_text))
    print()
    if clean is None:
        print("CLEANED: <not present in sidecar>")
        return 0
    _print_cleaned(clean, raw_text, wrap)
    print("PROVENANCE:")
    print("-" * 92)
    for k in ("model_id", "prompt_sha256", "input_sha256", "output_sha256",
             "generated_at", "cleanup_skipped"):
        if k in clean:
            print(f"  {k}: {clean[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
