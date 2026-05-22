"""Aggregate per-page review-priority scores into a single JSON.

Sprint 4l-E. Reads ``pages.jsonl`` + ``pages_cleaned.jsonl`` (+ optional
``pages_cleaned_qc.jsonl`` when present), computes
``pursue_index.clean.qc.priority.score_page`` per page, and writes a
sorted-descending top-K queue to
``web/public/data/review-priority.json``.

Usage::

    python scripts/build_review_priority.py [--limit 200]

Defaults: every PDF card in the latest manifest; full output (no limit).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pursue_index.clean.qc.priority import score_page  # noqa: E402

DEFAULT_OCR_DIR = Path("/mnt/nas/personal/pursue/ocr")
DEFAULT_OUT = _REPO_ROOT / "web" / "public" / "data" / "review-priority.json"
DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return rows


def _qc_verdict_by_page(qc_path: Path) -> dict[int, str | None]:
    out: dict[int, str | None] = {}
    for row in _load_jsonl(qc_path):
        page = row.get("page")
        if not isinstance(page, int):
            continue
        agg = row.get("aggregate", {}) if isinstance(row.get("aggregate"), dict) else {}
        out[page] = agg.get("verdict")
    return out


def score_card(card_id: str, card_dir: Path, *, qc_path: Path | None = None) -> list[dict]:
    raw_rows = _load_jsonl(card_dir / "pages.jsonl")
    cleaned_rows = _load_jsonl(card_dir / "pages_cleaned.jsonl")
    if not cleaned_rows:
        return []
    raw_by_page = {int(r.get("page", 0)): r for r in raw_rows}
    qc_by_page = _qc_verdict_by_page(qc_path) if qc_path else {}
    out: list[dict] = []
    for cleaned in cleaned_rows:
        page = int(cleaned.get("page", 0))
        raw_row = raw_by_page.get(page, {})
        priority = score_page(
            raw_text=raw_row.get("text", ""),
            cleaned_text=cleaned.get("text_cleaned", ""),
            ocr_confidence=float(raw_row.get("confidence", 0.0) or 0.0),
            qc_verdict=qc_by_page.get(page),
        )
        out.append({
            "card_id": card_id,
            "page": page,
            "review_priority": round(priority, 4),
            "ocr_confidence": raw_row.get("confidence"),
            "raw_sha256": cleaned.get("input_sha256"),
            "cleaned_sha256": cleaned.get("output_sha256"),
            "qc_verdict": qc_by_page.get(page),
        })
    return out


def _load_card_ids_from_manifest(manifest_path: Path) -> list[str]:
    data = json.loads(manifest_path.read_text())
    return [c["card_id"] for c in data.get("cards", []) if c.get("asset_type") == "PDF"]


def build(*, ocr_dir: Path, card_ids: list[str], out_path: Path, limit: int | None = None) -> None:
    all_pages: list[dict] = []
    for cid in card_ids:
        card_dir = ocr_dir / cid
        qc_path = card_dir / "pages_cleaned_qc.jsonl"
        scores = score_card(cid, card_dir, qc_path=qc_path if qc_path.exists() else None)
        all_pages.extend(scores)
    total = len(all_pages)
    all_pages.sort(key=lambda r: r["review_priority"], reverse=True)
    if limit is not None and limit > 0:
        all_pages = all_pages[:limit]
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "total_pages": len(all_pages),
        "corpus_total_pages": total,
        "pages": all_pages,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--limit", type=int, default=500,
                   help="Cap on the number of pages in the output queue. "
                        "Default 500 keeps the committed JSON small; pass "
                        "--limit 0 for the full corpus.")
    args = p.parse_args(argv)
    card_ids = _load_card_ids_from_manifest(args.manifest)
    build(ocr_dir=args.ocr_dir, card_ids=card_ids,
          out_path=args.out, limit=args.limit)
    print(f"build_review_priority: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
