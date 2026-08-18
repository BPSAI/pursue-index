"""One-shot repair for OCR-envelope artifact in
``data/altered-ocr/<card_id>/pages.jsonl`` (hotfix).

The Anthropic vision model occasionally returns the OCR text inside
a JSON envelope (``{"text": "...", "confidence": 99}``) but with
unescaped inner double-quotes — making the response unparseable as
JSON. ``pursue_index.ocr.llm._parse_response`` correctly detects the
failure and falls back to ``return raw`` — but that stuffs the
literal envelope INTO the ``text`` field of pages.jsonl. The diff
surface then shows the envelope string instead of the OCR text it
should contain.

This script walks every ``pages.jsonl`` under ``data/altered-ocr/``,
identifies rows whose ``text`` field matches the envelope pattern,
extracts the inner OCR text, unescapes the standard backslash
sequences (``\\n``, ``\\t``, ``\\\\``, ``\\"``), and rewrites the
file in place.

Per the affected scope (43 of 3,431 pages, 1.3%), this is a small
surgical hotfix — much faster than re-OCR'ing those pages. The
upstream parser fix is a separate concern (touches the canonical
``pursue_index.ocr.llm`` module; affects every future OCR run).

Idempotent: re-running on already-cleaned data is a no-op.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OCR_DIR = _REPO_ROOT / "data" / "altered-ocr"

# Matches the canonical envelope patterns we've observed in the
# committed data:
#   {\n  "text": "...", "confidence": 99\n}
#   ```json\n{...}\n```
# The pattern's leading-anchor is generous (allows leading whitespace,
# optional ``` fence) but the ``"text": "`` open is exact. Inner
# content is captured greedily; we trim from the back to find the
# matching close.
_ENVELOPE_OPEN = re.compile(
    r'^\s*(?:```(?:json)?\s*)?\{[\s\n]*"text"\s*:\s*"',
    re.IGNORECASE,
)

# Find the closing of the envelope: `", "confidence": <num>}` (with
# optional whitespace + optional trailing ``` fence).
_ENVELOPE_CLOSE = re.compile(
    r'"\s*,\s*"confidence"\s*:\s*\d+(?:\.\d+)?\s*\}\s*(?:```\s*)?$',
    re.IGNORECASE,
)


def looks_like_envelope(text: str) -> bool:
    """Detect the envelope-artifact pattern."""
    return bool(_ENVELOPE_OPEN.match(text))


def extract_envelope_text(raw: str) -> str | None:
    """Strip the envelope wrapper from ``raw`` and return the inner
    OCR text with standard escape sequences expanded.

    Returns None if the pattern doesn't match (caller falls back to
    keeping the raw value).
    """
    open_match = _ENVELOPE_OPEN.match(raw)
    close_match = _ENVELOPE_CLOSE.search(raw)
    if not (open_match and close_match):
        return None
    inner = raw[open_match.end():close_match.start()]
    # Unescape the standard JSON sequences. We do this manually
    # because json.loads() would refuse the unescaped inner quotes
    # that caused the original parse failure.
    inner = (
        inner.replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace("\\r", "\r")
             .replace('\\"', '"')
             .replace("\\\\", "\\")
    )
    return inner


def repair_jsonl(path: Path) -> tuple[int, int]:
    """Repair ``path`` in place. Returns (rows_repaired, rows_total)."""
    rows = []
    repaired = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        text = row.get("text", "")
        if looks_like_envelope(text):
            inner = extract_envelope_text(text)
            if inner is not None:
                row["text"] = inner
                repaired += 1
        rows.append(row)
    if repaired > 0:
        # Atomic rewrite via temp+rename.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    return repaired, len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    args = parser.parse_args(argv)

    total_repaired = 0
    total_pages = 0
    affected_cards = []
    for jsonl in sorted(args.ocr_dir.glob("*/pages.jsonl")):
        repaired, count = repair_jsonl(jsonl)
        total_pages += count
        if repaired > 0:
            total_repaired += repaired
            affected_cards.append((jsonl.parent.name, repaired, count))

    print(f"repair_altered_ocr_envelopes: {total_repaired} of {total_pages} pages repaired")
    if affected_cards:
        print(f"affected cards ({len(affected_cards)}):")
        for card_id, repaired, total in affected_cards:
            print(f"  {card_id}: {repaired}/{total} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
