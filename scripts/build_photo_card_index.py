#!/usr/bin/env python3
"""Build the allow-list of card_ids that are image-content-as-PDF.

Some PURSUE cards ship as `asset_type=PDF` but the PDF wraps a single
photograph rather than a text document. FBI Photos B001-B024 are the
canonical case — war.gov chose to publish those 24 FLIR stills as PDFs
while publishing the matching A-series (A001-A008) as PNGs. Operator
discovery hit the resulting filter gap: clicking "IMAGES" in the
gallery surfaced only the 14 `asset_type=IMG` cards and missed every
B-series photo.

This script emits ``web/src/data/photo-card-ids.json`` — an allow-list
of card_ids the gallery's PHOTOGRAPHS filter unions with the existing
`asset_type=IMG` set. The manifest's `asset_type` is left alone
(provenance integrity: that field reflects what war.gov published).

Predicate — a card is photo-content-PDF iff:
  - asset_type == "PDF" AND
  - page_count == 1 AND
  - the page's OCR text, after whitespace strip, is < 500 chars

The 500-char threshold separates the 25 B-series + 1 CENTCOM
declass-header card (DOW-UAP-PR020 Kuwait) from the next-densest
single-page PDF in the corpus (Pajarito Astronomers Invitation, 843
chars of real text). Re-survey if upstream pushes a card in the
500-850 chars range that should land on either side.

Usage::

    python scripts/build_photo_card_index.py
    python scripts/build_photo_card_index.py --manifest path.json --out path.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"
# Tracks PURSUE_DATA_ROOT rather than baking in one operator's mount point.
DEFAULT_OCR_ROOT = settings.ocr_dir
DEFAULT_OUT = REPO_ROOT / "web" / "src" / "data" / "photo-card-ids.json"

# Threshold for "page is image, not text". See module docstring for the
# survey that fixed this number. Bumping it would silently pull text
# documents into the PHOTOGRAPHS filter; lowering it would push real
# image cards back out.
TEXT_CHAR_THRESHOLD = 500


def is_photo_pdf(card: dict, page_count: int, page_text: str) -> bool:
    """Return True iff this card is a PDF-wrapped single photograph."""
    if card.get("asset_type") != "PDF":
        return False
    if page_count != 1:
        return False
    if len(page_text.strip()) >= TEXT_CHAR_THRESHOLD:
        return False
    return True


def _read_first_page_text(pages_jsonl: Path) -> str:
    """Read the first valid row from pages.jsonl and return its text."""
    if not pages_jsonl.exists():
        return ""
    with pages_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            return row.get("text", "") or ""
    return ""


def build(
    *, manifest_path: Path, ocr_root: Path, out_path: Path
) -> None:
    """Read manifest + OCR sidecars, write the photo-card-ids JSON."""
    manifest = json.loads(manifest_path.read_text())
    card_ids: list[str] = []
    for card in manifest.get("cards", []):
        cid = card.get("card_id")
        if not cid:
            continue
        meta_path = ocr_root / cid / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        page_count = meta.get("page_count") or 0
        text = _read_first_page_text(ocr_root / cid / "pages.jsonl")
        if is_photo_pdf(card, page_count=page_count, page_text=text):
            card_ids.append(cid)

    card_ids.sort()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "card_ids": card_ids,
        "count": len(card_ids),
        "generated_at": datetime.now(UTC).isoformat(),
        "threshold_chars": TEXT_CHAR_THRESHOLD,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ocr-root", type=Path, default=DEFAULT_OCR_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(manifest_path=args.manifest, ocr_root=args.ocr_root, out_path=args.out)
    out = json.loads(args.out.read_text())
    print(f"photo-card-ids: {out['count']} cards → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
