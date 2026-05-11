#!/usr/bin/env python3
"""Print raw + cleaned text for one page of one card, side-by-side in stdout.

Usage:
    .venv/bin/python scripts/spotcheck_view.py <card_id> <page>
"""

from __future__ import annotations

import json
import pathlib
import sys
import textwrap

ROOT = pathlib.Path("/mnt/nas/personal/pursue/ocr")


def find_row(path: pathlib.Path, page: int) -> dict | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("page") == page:
            return row
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    card, page = sys.argv[1], int(sys.argv[2])
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
    print("PROVENANCE:")
    print("-" * 92)
    for k in ("model_id", "prompt_sha256", "input_sha256", "output_sha256",
             "generated_at", "cleanup_skipped"):
        if k in clean:
            print(f"  {k}: {clean[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
