"""Classify the upstream change for each altered card by comparing
the PDF text layer of the pre-edit vs current bytes.

Output: ``data/altered-classification.json`` mapping each altered
card to a change-class that the /altered/<card_id>/ page surfaces
alongside (or instead of) the OCR diff.

Why this exists: the engine-matched OCR diff is materially
cleaner than the earlier Haiku-vs-Sonnet diff, but Sonnet OCR
of two byte-different PDFs is still non-deterministic — different
rasterized pixels produce subtly different OCR text even when the
embedded content didn't change. The PDF text layer is the
authoritative content representation: if it's byte-equal across two
PDFs, the upstream change was purely presentational (re-rasterization,
font subset rev, embedded-image re-encoding, metadata churn) and the
on-disk OCR diff is signal-less noise.

Classes:

- ``presentation_only`` — both PDFs have a text layer; after
  whitespace normalization, the text layers are byte-equal. Bytes
  changed; content didn't. Skip the OCR diff for these cards on the
  per-card page.
- ``content_changed`` — both PDFs have a text layer; text layers
  differ after normalization. There's a real upstream content edit;
  the OCR diff is meaningful.
- ``no_text_layer`` — at least one side has no extractable text
  layer (image-only PDFs from scanned originals). Can't tell from
  text alone whether content changed; the OCR diff is the best
  signal we have but should be presented with a caveat.
- ``asset_type_change`` — the oldest byte-history entry is a non-PDF
  asset (typically .mp4 from a video → PDF swap upstream). Pre-edit
  content doesn't exist as text; no text-diff is meaningful.

Idempotent: re-running produces a byte-stable JSON output keyed by
card_id. Reads PDFs from ``<PURSUE_DATA_ROOT>/r2-mirror/archive/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_OUT = _REPO_ROOT / "data" / "altered-classification.json"

# Whitespace normalization: collapse runs of whitespace (incl.
# newlines, tabs, NBSP, etc.) into a single space, strip leading +
# trailing. Catches the most common re-rasterization noise (re-flowed
# line breaks for identical content) without being so aggressive that
# real content changes get masked.
_WHITESPACE_RE = re.compile(r"\s+")


def extract_text_layer(pdf_bytes: bytes) -> tuple[list[str], bool]:
    """Extract per-page text via pypdfium2.

    Returns ``(per_page_texts, any_text_present)``. Pages with no
    extractable text (image-only) emit empty strings; the bool flag
    is true iff at least one page returned a non-trivial string.
    """
    from pypdfium2 import PdfDocument  # type: ignore[import-not-found]
    pdf = PdfDocument(pdf_bytes)
    pages_text: list[str] = []
    any_text = False
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_bounded() or ""
            finally:
                text_page.close()
            page.close()
            pages_text.append(text)
            if text.strip():
                any_text = True
    finally:
        pdf.close()
    return pages_text, any_text


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip. Used to ignore re-rasterization
    noise (line breaks shifting around) while preserving any real
    content delta."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _compare_text_layers(
    *, oldest: dict, current: dict, pre_path: Path, post_path: Path
) -> dict[str, Any]:
    """Inner text-layer comparison. Extracted to keep classify_card
    under the 50-line arch cap."""
    pre_pages, pre_has_text = extract_text_layer(pre_path.read_bytes())
    post_pages, post_has_text = extract_text_layer(post_path.read_bytes())
    if not (pre_has_text and post_has_text):
        return {
            "class": "no_text_layer",
            "pre_pages": len(pre_pages),
            "post_pages": len(post_pages),
            "pre_has_text": pre_has_text,
            "post_has_text": post_has_text,
        }
    pre_norm = "\n".join(normalize_text(p) for p in pre_pages)
    post_norm = "\n".join(normalize_text(p) for p in post_pages)
    pre_sha = hashlib.sha256(pre_norm.encode("utf-8")).hexdigest()
    post_sha = hashlib.sha256(post_norm.encode("utf-8")).hexdigest()
    same = pre_sha == post_sha
    return {
        "class": "presentation_only" if same else "content_changed",
        "pre_pages": len(pre_pages),
        "post_pages": len(post_pages),
        "pre_text_sha256": pre_sha,
        "post_text_sha256": post_sha,
        "pre_byte_sha256": oldest["byte_sha256"],
        "post_byte_sha256": current["byte_sha256"],
    }


def classify_card(
    *, card_id: str, entries: list[dict], archive_dir: Path
) -> dict[str, Any] | None:
    """Return the classification record for a single multi-sha card,
    or None if the card has fewer than 2 entries."""
    if len(entries) < 2:
        return None
    current = entries[0]
    oldest = entries[-1]
    if not oldest.get("archive_key", "").lower().endswith(".pdf"):
        return {
            "class": "asset_type_change",
            "pre_archive_key": oldest.get("archive_key", ""),
            "post_archive_key": current.get("archive_key", ""),
            "note": "oldest byte-history entry is non-PDF (video→PDF swap);"
            " no text-layer comparison possible.",
        }
    pre_path = archive_dir / f"{oldest['byte_sha256']}.pdf"
    post_path = archive_dir / f"{current['byte_sha256']}.pdf"
    if not pre_path.exists() or not post_path.exists():
        return {
            "class": "no_text_layer",
            "note": f"PDF bytes missing on disk (pre={pre_path.exists()}, "
            f"post={post_path.exists()}).",
        }
    return _compare_text_layers(
        oldest=oldest, current=current, pre_path=pre_path, post_path=post_path
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Content-addressed PDF mirror. Defaults to "
        "``<PURSUE_DATA_ROOT>/r2-mirror/archive``.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.archive_dir is None:
        from pursue_index.config import settings  # type: ignore[import-not-found]
        args.archive_dir = settings.data_root / "r2-mirror" / "archive"

    bh = json.loads(args.byte_history.read_text(encoding="utf-8"))
    cards: dict[str, dict] = {}
    counts = {
        "presentation_only": 0, "content_changed": 0,
        "no_text_layer": 0, "asset_type_change": 0,
    }
    for card_id in sorted(bh.keys()):
        result = classify_card(
            card_id=card_id, entries=bh[card_id], archive_dir=args.archive_dir
        )
        if result is None:
            continue
        cards[card_id] = result
        counts[result["class"]] = counts.get(result["class"], 0) + 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"_meta": {"counts": counts, "card_count": len(cards)}, "cards": cards},
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"classify_altered_changes: {len(cards)} card(s) → {args.out}")
    for cls, n in counts.items():
        print(f"  {cls}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
