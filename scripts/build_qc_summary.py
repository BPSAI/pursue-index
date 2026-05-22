"""Aggregate ``pages_cleaned_qc.jsonl`` across the corpus into a
single snapshot for the methodology page.

Sprint 4l-D. Output lives at
``web/public/data/clean-qc-snapshot.json`` and powers the methodology
aggregate-stats block. Generates an "empty" snapshot when no QC data
exists yet — the methodology page renders a "pending" state in that
case rather than failing.

Output shape::

    {
      "schema_version": 1,
      "generated_at": "...Z",
      "judge_model": "claude-sonnet-4-6",
      "judge_prompt_sha256": "...",
      "total_pages_graded": N,
      "graded_pass_count": ...,
      "graded_soft_fail_count": ...,
      "graded_hard_fail_count": ...,
      "graded_not_applicable_count": ...,
      "judge_skipped_count": ...,
      "judge_skipped_by_reason": {"content_filter": N, "parse_failure": M},
      "cards_with_qc": N,
      "cards_listed_total": M
    }
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

DEFAULT_OCR_DIR = Path("/mnt/nas/personal/pursue/ocr")
DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "data" / "manifests" / "latest.json"
DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "web" / "public" / "data" / "clean-qc-snapshot.json"
)


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


def _empty_snapshot() -> dict:
    return {
        "total_pages_graded": 0,
        "graded_pass_count": 0,
        "graded_soft_fail_count": 0,
        "graded_hard_fail_count": 0,
        "graded_not_applicable_count": 0,
        "judge_skipped_count": 0,
        "judge_skipped_by_reason": {},
        "cards_with_qc": 0,
        "judge_model": None,
        "judge_prompt_sha256": None,
    }


def _accumulate_row(row: dict, snap: dict) -> None:
    snap["total_pages_graded"] += 1
    skip = row.get("judge_skipped")
    if skip:
        snap["judge_skipped_count"] += 1
        snap["judge_skipped_by_reason"][skip] = (
            snap["judge_skipped_by_reason"].get(skip, 0) + 1
        )
    agg = row.get("aggregate", {})
    verdict = agg.get("verdict") if isinstance(agg, dict) else None
    if verdict == "pass":
        snap["graded_pass_count"] += 1
    elif verdict == "soft_fail":
        snap["graded_soft_fail_count"] += 1
    elif verdict == "hard_fail":
        snap["graded_hard_fail_count"] += 1
    elif verdict == "not_applicable":
        snap["graded_not_applicable_count"] += 1


def aggregate(*, ocr_dir: Path, card_ids: list[str]) -> dict:
    """Walk per-card QC sidecars and roll up corpus-wide counts."""
    snap = _empty_snapshot()
    for cid in card_ids:
        qc_path = ocr_dir / cid / "pages_cleaned_qc.jsonl"
        rows = _load_jsonl(qc_path)
        if not rows:
            continue
        snap["cards_with_qc"] += 1
        for row in rows:
            _accumulate_row(row, snap)
            if snap["judge_model"] is None:
                snap["judge_model"] = row.get("judge_model_id")
                snap["judge_prompt_sha256"] = row.get("judge_prompt_sha256")
    return snap


def _load_card_ids_from_manifest(manifest_path: Path) -> list[str]:
    data = json.loads(manifest_path.read_text())
    return [c["card_id"] for c in data.get("cards", []) if c.get("asset_type") == "PDF"]


def build(*, ocr_dir: Path, card_ids: list[str], out_path: Path) -> None:
    snapshot = aggregate(ocr_dir=ocr_dir, card_ids=card_ids)
    snapshot["schema_version"] = 1
    snapshot["generated_at"] = dt.datetime.now(dt.UTC).isoformat()
    snapshot["cards_listed_total"] = len(card_ids)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    card_ids = _load_card_ids_from_manifest(args.manifest)
    build(ocr_dir=args.ocr_dir, card_ids=card_ids, out_path=args.out)
    print(f"build_qc_summary: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
