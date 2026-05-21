"""Sentence-level text diff between pre-edit OCR and post-edit OCR
for the 70 altered PDF cards (Sprint 4h Phase 2).

Inputs:
  * Pre-edit OCR: ``web/public/data/pages-cleaned.json`` (built
    2026-05-12 from the pre-overlay PDF versions). Shape:
    ``{"meta": ..., "pages": [{"card_id", "page", "text",
    "confidence"}, ...]}``.
  * Post-edit OCR: ``data/altered-ocr/<card_id>/pages.jsonl`` (Phase 1
    output). One row per page: ``{"page", "text", "confidence",
    "byte_sha256"}``.

Output:
  * ``web/src/data/altered-diffs.json``. SSR-imported by the
    per-card diff page; build-time data, not a runtime fetch. Shape:

      {
        "<card_id>": {
          "pages": [
            {
              "page_no": 1,
              "segments": [
                {"kind": "equal" | "removed" | "added", "text": "..."}
              ]
            },
            ...
          ],
          "summary": {
            "removed_words": 247,
            "added_words": 3,
            "modified_pages": [3, 4, 5, 7],
            "first_change_page": 3
          }
        },
        ...
      }

Algorithm: sentence-level diff via difflib.SequenceMatcher on
sentence-split inputs. Sentence-level (not line-level) because OCR
introduces spurious line breaks; sentence boundaries are stable.

Pure-Python stdlib only. Deterministic + idempotent. No API spend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Sentence diff helpers extracted to keep this script under arch caps.
from _diff_algorithm import (  # noqa: E402
    diff_sentences,
    split_sentences,
    summarize_diff,
    word_count as _word_count,
)

DEFAULT_PRE_OCR = _REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"
DEFAULT_ALTERED_PRE_OCR_DIR = _REPO_ROOT / "data" / "altered-ocr-pre"
DEFAULT_POST_OCR_DIR = _REPO_ROOT / "data" / "altered-ocr"
DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_CLASSIFICATION = _REPO_ROOT / "data" / "altered-classification.json"
DEFAULT_OUT = _REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"


def _diff_one_page(
    page_no: int, pre_text: str, post_text: str
) -> tuple[dict, int, int, int]:
    """Diff one page; return (page_diff_dict, removed_words, added_words,
    modified_sentences). Extracted to keep ``build_card_diff`` under
    the 50-line ceiling (nayru/vaivora H1)."""
    segments = diff_sentences(pre_text, post_text)
    s = summarize_diff(segments)
    return (
        {"page_no": page_no, "segments": segments},
        s["removed_words"],
        s["added_words"],
        s["modified_sentences"],
    )


def _classify_ocr_status(pre_max: int, post_max: int) -> str:
    """Symmetric coverage classification (nayru/vaivora H3):

    * ``complete`` — pre_max == post_max (typical).
    * ``partial`` — post_max < pre_max (content-filter truncation
      or upstream removed pages; OCR may be incomplete on the
      post-edit side).
    * ``post_extended`` — post_max > pre_max (upstream re-published
      with ADDED pages; pre-edit OCR has no text for the new ones
      so any "added" content would render as wholesale insert).
    """
    if post_max == 0 or pre_max == 0:
        return "complete"
    if post_max < pre_max:
        return "partial"
    if post_max > pre_max:
        return "post_extended"
    return "complete"


def _candidate_pages(
    pre_by_page: dict[int, str],
    post_by_page: dict[int, str],
    ocr_status: str,
    post_max: int,
) -> list[int]:
    """Decide which page numbers to diff given the coverage status.

    * complete: every page on either side.
    * partial (post truncated, e.g., content-filter trip): every
      page where post has OCR. Pre-only pages past ``post_max``
      are EXCLUDED so they don't render as "all removed" — that
      would frame OCR truncation as redaction (nayru/vaivora H3
      partial-side guard).
    * post_extended (upstream re-published longer): every page on
      either side. Post-only pages past pre_max render as wholesale
      additions, which is the truthful framing.
    """
    all_keys = set(pre_by_page.keys()) | set(post_by_page.keys())
    if ocr_status == "partial":
        all_keys = {p for p in all_keys if p <= post_max}
    return sorted(all_keys)


def build_card_diff(pre_pages: list[dict], post_pages: list[dict]) -> dict:
    """Build the diff structure for one card.

    Symmetric coverage: ``ocr_status`` distinguishes complete /
    partial / post_extended so the diff page can banner each
    case correctly (nayru/vaivora H3). Pre-fix the post>pre case
    silently dropped added pages from the diff, mis-framing a
    longer-document re-publish as no-change.
    """
    pre_by_page = {p["page"]: p.get("text", "") for p in pre_pages}
    post_by_page = {p["page"]: p.get("text", "") for p in post_pages}
    if not pre_by_page and not post_by_page:
        return _empty_diff()
    pre_max = max(pre_by_page.keys()) if pre_by_page else 0
    post_max = max(post_by_page.keys()) if post_by_page else 0
    ocr_status = _classify_ocr_status(pre_max, post_max)
    pages_to_diff = _candidate_pages(pre_by_page, post_by_page, ocr_status, post_max)

    page_diffs: list[dict] = []
    modified_pages: list[int] = []
    total_removed = 0
    total_added = 0
    total_modified = 0
    for page_no in pages_to_diff:
        page_diff, removed, added, modified = _diff_one_page(
            page_no,
            pre_by_page.get(page_no, ""),
            post_by_page.get(page_no, ""),
        )
        page_diffs.append(page_diff)
        total_removed += removed
        total_added += added
        total_modified += modified
        if removed > 0 or added > 0 or modified > 0:
            modified_pages.append(page_no)

    return {
        "pages": page_diffs,
        "summary": {
            "removed_words": total_removed,
            "added_words": total_added,
            "modified_sentences": total_modified,
            "modified_pages": modified_pages,
            "first_change_page": modified_pages[0] if modified_pages else None,
            "ocr_status": ocr_status,
            "ocr_max_page": post_max,
            "total_pre_pages": pre_max,
        },
    }


def _empty_diff() -> dict:
    return {
        "pages": [],
        "summary": {
            "removed_words": 0,
            "added_words": 0,
            "modified_sentences": 0,
            "modified_pages": [],
            "first_change_page": None,
            "ocr_status": "complete",
            "ocr_max_page": 0,
            "total_pre_pages": 0,
        },
    }


def _pre_ocr_sha(pages_cleaned_path: Path) -> str:
    """Hash ``pages-cleaned.json`` bytes; pinned in the diff's _meta so
    a re-build can detect the source shifted under us (vaivora H4)."""
    return hashlib.sha256(pages_cleaned_path.read_bytes()).hexdigest()


def _load_post_ocr(card_dir: Path) -> list[dict]:
    """Parse data/altered-ocr/<card_id>/pages.jsonl → [{page, text}]."""
    jsonl = card_dir / "pages.jsonl"
    if not jsonl.is_file():
        return []
    rows: list[dict] = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append({"page": obj["page"], "text": obj.get("text", "")})
    rows.sort(key=lambda r: r["page"])
    return rows


def _load_altered_pre_ocr(card_dir: Path) -> list[dict]:
    """Parse data/altered-ocr-pre/<card_id>/pages.jsonl → [{page, text}].

    Sprint 4j: when the engine-matched pre-edit OCR exists for a card,
    use it instead of the legacy ``pages-cleaned.json`` entry. Keeps the
    diff apples-to-apples (both sides produced by the same vision
    model), which is the load-bearing assumption of sentence-level
    difflib. Falls back to ``pages-cleaned.json`` for cards whose
    engine-matched pre-edit isn't available.
    """
    return _load_post_ocr(card_dir)


def _build_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-ocr", type=Path, default=DEFAULT_PRE_OCR)
    parser.add_argument(
        "--altered-pre-ocr-dir",
        type=Path,
        default=DEFAULT_ALTERED_PRE_OCR_DIR,
        help="Engine-matched pre-edit OCR per altered card. Overrides "
        "--pre-ocr for any card with a pages.jsonl present.",
    )
    parser.add_argument("--post-ocr-dir", type=Path, default=DEFAULT_POST_OCR_DIR)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument(
        "--classification",
        type=Path,
        default=DEFAULT_CLASSIFICATION,
        help="Per-card change classification from "
        "`scripts/classify_altered_changes.py`. When a card is classified "
        "`presentation_only` (text layer byte-equal across pre/post), the "
        "OCR diff is dropped — it's Sonnet non-determinism noise on "
        "byte-different but content-identical PDFs.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser


def _load_classification(path: Path) -> dict[str, dict]:
    """Returns {card_id: {class, ...}} or {} if no classification file."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("cards", {})


def _diff_one_card(
    card_id: str, *, byte_history: dict, altered_pre_ocr_dir: Path,
    post_ocr_dir: Path,
) -> tuple[str, dict | None]:
    """Extracted from main() to honor the 50-line cap. Status is one of
    ``engine_matched`` / ``skipped_asset_type`` / ``skipped_missing_pre`` /
    ``skipped_no_post``. Asset-type-swap cards (oldest entry non-PDF)
    fall through to "TEXT DIFF NOT AVAILABLE" on the per-card page.
    """
    post_pages = _load_post_ocr(post_ocr_dir / card_id)
    if not post_pages:
        return "skipped_no_post", None
    entries = byte_history.get(card_id, [])
    if entries and not entries[-1].get("archive_key", "").lower().endswith(".pdf"):
        return "skipped_asset_type", None
    altered_pre = _load_altered_pre_ocr(altered_pre_ocr_dir / card_id)
    if not altered_pre:
        print(
            f"::warning::skip {card_id}: no engine-matched pre-edit OCR "
            f"at {altered_pre_ocr_dir / card_id}; rerun "
            "`scripts/reocr_pre_edit_altered.py`.",
            file=sys.stderr,
        )
        return "skipped_missing_pre", None
    return "engine_matched", build_card_diff(altered_pre, post_pages)


def main(argv: list[str] | None = None) -> int:
    args = _build_args_parser().parse_args(argv)
    pre_sha = _pre_ocr_sha(args.pre_ocr)
    byte_history = json.loads(args.byte_history.read_text(encoding="utf-8"))
    classification = _load_classification(args.classification)

    diffs: dict[str, dict] = {}
    engine_matched: list[str] = []
    skipped_asset_type_change: list[str] = []
    skipped_presentation_only: list[str] = []
    for card_id in sorted(byte_history.keys()):
        # Sprint 4k-A + 4k-B: skip OCR diff for cards confirmed as
        # content-identical via the text layer (presentation_only) OR
        # via perceptual-hash image comparison (visually_identical).
        # In both cases the bytes shifted but the content didn't, so
        # any OCR diff is non-determinism noise.
        card_info = classification.get(card_id, {})
        if (
            card_info.get("class") == "presentation_only"
            or card_info.get("visual_class") == "visually_identical"
        ):
            skipped_presentation_only.append(card_id)
            continue
        status, card_diff = _diff_one_card(
            card_id,
            byte_history=byte_history,
            altered_pre_ocr_dir=args.altered_pre_ocr_dir,
            post_ocr_dir=args.post_ocr_dir,
        )
        if status == "engine_matched":
            engine_matched.append(card_id)
            diffs[card_id] = card_diff  # type: ignore[assignment]
        elif status == "skipped_asset_type":
            skipped_asset_type_change.append(card_id)

    # vaivora H4: pin the pre-edit OCR source sha256 in the output's
    # meta block. If pages-cleaned.json ever gets re-generated from
    # post-edit bytes (after a future OCR pass), the sha will mismatch
    # and operators can detect the diff is stale before re-publishing.
    output = {
        "_meta": {
            "pre_ocr_source": str(args.pre_ocr.relative_to(_REPO_ROOT)) if args.pre_ocr.is_absolute() else str(args.pre_ocr),
            "pre_ocr_sha256": pre_sha,
            "altered_pre_ocr_dir": str(
                args.altered_pre_ocr_dir.relative_to(_REPO_ROOT)
            ) if args.altered_pre_ocr_dir.is_absolute() else str(args.altered_pre_ocr_dir),
            "engine_matched_cards": sorted(engine_matched),
            "skipped_asset_type_change_cards": sorted(skipped_asset_type_change),
            "skipped_presentation_only_cards": sorted(skipped_presentation_only),
            "card_count": len(diffs),
        },
        "classification": classification,
        "diffs": diffs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"build_altered_diffs: {len(diffs)} card(s) → {args.out} "
        f"({len(engine_matched)} engine-matched diff; "
        f"{len(skipped_presentation_only)} presentation-only skipped; "
        f"{len(skipped_asset_type_change)} asset-type-swap skipped)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
