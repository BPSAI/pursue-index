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
import difflib
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PRE_OCR = _REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"
DEFAULT_POST_OCR_DIR = _REPO_ROOT / "data" / "altered-ocr"
DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_OUT = _REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"


_SENTENCE_SPLITTER = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Sentence boundary = ``.``/``!``/``?``
    followed by whitespace. Collapses internal whitespace; drops empty
    segments.

    OCR-friendly: keeps the terminator with each sentence so a viewer
    can rebuild the original layout sentence-by-sentence.
    """
    if not text or not text.strip():
        return []
    parts = _SENTENCE_SPLITTER.split(text.strip())
    out = []
    for p in parts:
        # Collapse internal whitespace (newlines + tabs from OCR
        # rasterization).
        normalized = re.sub(r"\s+", " ", p).strip()
        if normalized:
            out.append(normalized)
    return out


def diff_sentences(before: str, after: str) -> list[dict]:
    """Sentence-level diff. Returns a list of segments with
    ``kind ∈ {"equal", "removed", "added"}``.

    Uses ``difflib.SequenceMatcher`` against the sentence-tokenized
    inputs. Adjacent same-kind chunks are merged so the renderer can
    treat a multi-sentence redaction as a single block.
    """
    pre = split_sentences(before)
    post = split_sentences(after)
    matcher = difflib.SequenceMatcher(a=pre, b=post, autojunk=False)
    segments: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segments.append({"kind": "equal", "text": " ".join(pre[i1:i2])})
        elif tag == "delete":
            segments.append({"kind": "removed", "text": " ".join(pre[i1:i2])})
        elif tag == "insert":
            segments.append({"kind": "added", "text": " ".join(post[j1:j2])})
        elif tag == "replace":
            # Treat replace as remove + add adjacent — keeps the
            # segment kinds simple ({equal,removed,added} only) and
            # lets the renderer decide whether to visually pair them.
            segments.append({"kind": "removed", "text": " ".join(pre[i1:i2])})
            segments.append({"kind": "added", "text": " ".join(post[j1:j2])})
    # Drop empty segments (can occur if both sides have only whitespace).
    return [s for s in segments if s["text"].strip()]


_WORD_RE = re.compile(r"\b\w+\b")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def summarize_diff(segments: list[dict]) -> dict:
    """Aggregate stats over a flat segment list (or a single page's
    segments). Used both at the page level (for sub-totals if needed)
    and at the card level (after concatenating all pages' segments).
    """
    removed = sum(_word_count(s["text"]) for s in segments if s["kind"] == "removed")
    added = sum(_word_count(s["text"]) for s in segments if s["kind"] == "added")
    return {"removed_words": removed, "added_words": added}


def build_card_diff(pre_pages: list[dict], post_pages: list[dict]) -> dict:
    """Build the diff structure for one card. Pairs pages by page_no;
    pages present in only one side become wholesale add/remove.

    Detects partial post-edit OCR (e.g., content-filter rejected
    pages mid-card): when the highest post-edit page is less than
    the highest pre-edit page, only diff the overlapping range and
    mark ``ocr_status: "partial"`` so the diff page can render a
    "OCR incomplete past page N" banner. Without this, pages N+1
    through end-of-pre would render as "everything removed" — a
    misleading framing of redaction that's actually OCR truncation.
    """
    pre_by_page = {p["page"]: p.get("text", "") for p in pre_pages}
    post_by_page = {p["page"]: p.get("text", "") for p in post_pages}
    if not pre_by_page and not post_by_page:
        return _empty_diff()
    pre_max = max(pre_by_page.keys()) if pre_by_page else 0
    post_max = max(post_by_page.keys()) if post_by_page else 0
    # If post-edit OCR is incomplete (post_max < pre_max), constrain
    # the diff to the overlap and surface the truncation.
    ocr_partial = post_max > 0 and post_max < pre_max
    diff_max = min(pre_max, post_max) if (pre_max and post_max) else max(pre_max, post_max)
    all_pages = sorted({
        p for p in (set(pre_by_page.keys()) | set(post_by_page.keys()))
        if p <= diff_max
    })

    page_diffs: list[dict] = []
    modified_pages: list[int] = []
    total_removed = 0
    total_added = 0
    for page_no in all_pages:
        pre_text = pre_by_page.get(page_no, "")
        post_text = post_by_page.get(page_no, "")
        segments = diff_sentences(pre_text, post_text)
        page_summary = summarize_diff(segments)
        page_diffs.append({"page_no": page_no, "segments": segments})
        total_removed += page_summary["removed_words"]
        total_added += page_summary["added_words"]
        if page_summary["removed_words"] > 0 or page_summary["added_words"] > 0:
            modified_pages.append(page_no)

    return {
        "pages": page_diffs,
        "summary": {
            "removed_words": total_removed,
            "added_words": total_added,
            "modified_pages": modified_pages,
            "first_change_page": modified_pages[0] if modified_pages else None,
            "ocr_status": "partial" if ocr_partial else "complete",
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
            "modified_pages": [],
            "first_change_page": None,
            "ocr_status": "complete",
            "ocr_max_page": 0,
            "total_pre_pages": 0,
        },
    }


def _load_pre_ocr_by_card(pages_cleaned_path: Path) -> dict[str, list[dict]]:
    """Parse pages-cleaned.json → {card_id: [{page, text}, ...]}."""
    blob = json.loads(pages_cleaned_path.read_text(encoding="utf-8"))
    pages_by_card: dict[str, list[dict]] = {}
    for row in blob.get("pages", []):
        card_id = row.get("card_id")
        if not card_id:
            continue
        pages_by_card.setdefault(card_id, []).append({
            "page": row["page"],
            "text": row.get("text", ""),
        })
    # Ensure each card's pages are sorted by page_no.
    for pages in pages_by_card.values():
        pages.sort(key=lambda p: p["page"])
    return pages_by_card


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-ocr", type=Path, default=DEFAULT_PRE_OCR)
    parser.add_argument("--post-ocr-dir", type=Path, default=DEFAULT_POST_OCR_DIR)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    pre_by_card = _load_pre_ocr_by_card(args.pre_ocr)
    byte_history = json.loads(args.byte_history.read_text(encoding="utf-8"))

    diffs: dict[str, dict] = {}
    for card_id in sorted(byte_history.keys()):
        post_pages = _load_post_ocr(args.post_ocr_dir / card_id)
        if not post_pages:
            # No post-edit OCR yet (Phase 1 may still be running, or
            # this card is a .mp4 video — skipped from OCR). The diff
            # page will degrade gracefully; no entry in altered-diffs.
            continue
        pre_pages = pre_by_card.get(card_id, [])
        diff = build_card_diff(pre_pages, post_pages)
        diffs[card_id] = diff

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(diffs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"build_altered_diffs: {len(diffs)} card(s) → {args.out}"
        f" (skipped {len(byte_history) - len(diffs)} without post-edit OCR)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
