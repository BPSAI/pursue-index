"""Visually classify the cards that ``classify_altered_changes.py``
left as ``no_text_layer`` (image-only PDFs, typically scanned
declassified documents).

For each such card, rasterize both pre-edit and current bytes,
compute a perceptual hash per page, and tally bit differences. If
every page's pre/post hash is within a small bit-difference
tolerance, the upstream change was visually identical to the eye
(re-encoded JPEG, different scanner color profile, etc.) — no real
content change. Otherwise the visual difference is real.

This is the Sprint 4k-B complement to 4k-A: 4k-A used the embedded
text layer where available; this fills in the 56 cards that have no
text layer because the source is image-only.

Output: extends ``data/altered-classification.json`` with a
``visual_class`` and per-card stats. Schema is additive so the file
remains consumable by anyone reading just the prior `class` field.

No new third-party deps: uses PIL + pdf2image (in venv).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_CLASSIFICATION = _REPO_ROOT / "data" / "altered-classification.json"

# Average-hash (aHash) size — small enough to be fast, large enough to
# distinguish meaningful visual changes from compression noise.
_HASH_SIZE = 64

# Per-page bit-diff threshold: pre/post hashes are considered "visually
# equivalent" if the Hamming distance is < this.
#
# Calibration (Sprint 4k-recal, against operator eyeball verification):
#   - `48e4bc1bdb5a66e8` at max bit-diff 131/4096 → operator confirmed
#     zero visible change (handwritten memo, scan re-encoding noise).
#   - `e93f6997811954dc` at max bit-diff 294/4096 → operator confirmed
#     a small real edit on the high-diff pages, but most pages identical.
#   - Original threshold 32 was tuned against synthetic checkerboard
#     tests, not real PDF rescans; produced ~80% false positives in
#     production.
#
# 250 splits the calibration: 131 (zero change) is below; 294 (some
# real change) is above. Conservative interpretation — cards above the
# threshold MAY have real changes but the visual signal alone isn't
# sufficient to confirm; downstream UI surfaces this as uncertain.
_PER_PAGE_BIT_THRESHOLD = 250

# Rasterization DPI. Lower than OCR's 200 (we don't need text-level
# resolution for visual hashing); cuts time per page ~4x.
_RASTER_DPI = 100


def perceptual_hash(image: Any) -> bytes:
    """Average-hash an image to ``_HASH_SIZE × _HASH_SIZE`` bits.

    Converts to grayscale, resizes to the hash dimensions, then
    thresholds against the image mean. Returns packed bytes so the
    Hamming distance between hashes is a single ``int.bit_count()``
    call on the XOR.
    """
    from PIL import Image  # type: ignore[import-not-found]
    gray = image.convert("L").resize(
        (_HASH_SIZE, _HASH_SIZE), Image.Resampling.LANCZOS
    )
    pixels = list(gray.tobytes())
    mean = sum(pixels) / len(pixels)
    bits = bytearray((len(pixels) + 7) // 8)
    for i, px in enumerate(pixels):
        if px > mean:
            bits[i // 8] |= 1 << (i % 8)
    return bytes(bits)


def hamming_distance(a: bytes, b: bytes) -> int:
    """Bit-difference between two equal-length byte sequences."""
    if len(a) != len(b):
        raise ValueError(f"hash length mismatch: {len(a)} vs {len(b)}")
    return int.from_bytes(
        bytes(x ^ y for x, y in zip(a, b)), "big"
    ).bit_count()


def hash_pdf_pages(pdf_bytes: bytes) -> list[bytes]:
    """Rasterize a PDF and return one perceptual hash per page."""
    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]
    images = convert_from_bytes(pdf_bytes, dpi=_RASTER_DPI)
    return [perceptual_hash(img) for img in images]


def compare_visuals(
    pre_path: Path, post_path: Path
) -> dict[str, Any]:
    """Compute per-page bit differences and a card-level classification."""
    pre_hashes = hash_pdf_pages(pre_path.read_bytes())
    post_hashes = hash_pdf_pages(post_path.read_bytes())
    if len(pre_hashes) != len(post_hashes):
        return {
            "visual_class": "page_count_changed",
            "pre_pages": len(pre_hashes),
            "post_pages": len(post_hashes),
        }
    per_page = [hamming_distance(a, b) for a, b in zip(pre_hashes, post_hashes)]
    max_diff = max(per_page) if per_page else 0
    avg_diff = sum(per_page) / len(per_page) if per_page else 0
    visual_class = (
        "visually_identical" if max_diff < _PER_PAGE_BIT_THRESHOLD
        else "visually_changed"
    )
    return {
        "visual_class": visual_class,
        "pages": len(per_page),
        "max_page_bit_diff": max_diff,
        "avg_page_bit_diff": round(avg_diff, 2),
        "threshold": _PER_PAGE_BIT_THRESHOLD,
        "hash_size_bits": _HASH_SIZE * _HASH_SIZE,
    }


def classify_card_visually(
    *, card_id: str, entry: dict, byte_history: dict, archive_dir: Path
) -> dict[str, Any] | None:
    """Process one card visually. Originally targeted no_text_layer
    cards only, but also runs on content_changed cards (Sprint 4k-QC
    feedback): some text-layer differences are pure whitespace /
    tokenization shifts internal to the PDF; if the rendered images
    are visually identical, the effective classification is
    presentation_only.

    Returns the extra fields to merge into the existing classification
    entry, or None on skip."""
    eligible = {"no_text_layer", "content_changed"}
    if entry.get("class") not in eligible:
        return None
    bh = byte_history.get(card_id, [])
    if len(bh) < 2:
        return None
    current = bh[0]
    oldest = bh[-1]
    if not (oldest.get("archive_key", "").lower().endswith(".pdf") and
            current.get("archive_key", "").lower().endswith(".pdf")):
        return None
    pre_path = archive_dir / f"{oldest['byte_sha256']}.pdf"
    post_path = archive_dir / f"{current['byte_sha256']}.pdf"
    if not (pre_path.exists() and post_path.exists()):
        return None
    return compare_visuals(pre_path, post_path)


def _run(args: argparse.Namespace) -> int:
    classification = json.loads(args.classification.read_text(encoding="utf-8"))
    byte_history = json.loads(args.byte_history.read_text(encoding="utf-8"))
    cards = classification.get("cards", {})

    visual_counts: dict[str, int] = {}
    processed = 0
    for card_id, entry in cards.items():
        extra = classify_card_visually(
            card_id=card_id, entry=entry,
            byte_history=byte_history, archive_dir=args.archive_dir,
        )
        if extra is None:
            continue
        entry.update(extra)
        vc = extra.get("visual_class", "unknown")
        visual_counts[vc] = visual_counts.get(vc, 0) + 1
        processed += 1
        if processed % 5 == 0 or processed == 1:
            print(f"  [{processed}] {card_id}: {vc} "
                  f"(max bit-diff: {extra.get('max_page_bit_diff')})")

    classification.setdefault("_meta", {})["visual_counts"] = visual_counts
    args.classification.write_text(
        json.dumps(classification, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nclassify_no_text_layer_visually: {processed} card(s) processed")
    for vc, n in visual_counts.items():
        print(f"  {vc}: {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Content-addressed PDF mirror. Defaults to "
        "``<PURSUE_DATA_ROOT>/r2-mirror/archive``.",
    )
    args = parser.parse_args(argv)
    if args.archive_dir is None:
        from pursue_index.config import settings  # type: ignore[import-not-found]
        args.archive_dir = settings.data_root / "r2-mirror" / "archive"
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
