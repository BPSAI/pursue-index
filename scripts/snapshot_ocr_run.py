#!/usr/bin/env python3
"""Snapshot per-card mean confidence + duration from the current OCR output.

Walks ``settings.ocr_dir`` and writes ``data/benchmarks/_{label}-snapshot.json``
with one record per card: ``{card_id, engine, pages, mean_conf, duration_s}``.
Used to capture the full-corpus baseline for a given engine before/after a
re-OCR pass.

Run::

    .venv/bin/python scripts/snapshot_ocr_run.py --label surya
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "benchmarks"


def collect_records(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    title_by_id = {c["card_id"]: c.get("title", "") for c in manifest["cards"]}
    agency_by_id = {c["card_id"]: c.get("agency", "") for c in manifest["cards"]}
    redacted_by_id = {c["card_id"]: c.get("redacted", False) for c in manifest["cards"]}

    records = []
    if not settings.ocr_dir.exists():
        return records
    for d in sorted(settings.ocr_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta_path = d / "meta.json"
        pages_path = d / "pages.jsonl"
        if not (meta_path.exists() and pages_path.exists()):
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("status") != "ok":
            continue
        confs = []
        n_pages = 0
        with pages_path.open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                confs.append(row.get("confidence", 0))
                n_pages += 1
        records.append({
            "card_id": d.name,
            "engine": meta.get("engine"),
            "pages": n_pages,
            "mean_conf": sum(confs) / len(confs) if confs else 0,
            "duration_s": meta.get("duration_s"),
            "pdf_bytes": meta.get("pdf_bytes"),
            "agency": agency_by_id.get(d.name, ""),
            "title": title_by_id.get(d.name, ""),
            "redacted": redacted_by_id.get(d.name, False),
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="snapshot label, e.g. surya")
    parser.add_argument("--manifest", type=Path,
                        default=REPO_ROOT / "data" / "manifests" / "latest.json")
    args = parser.parse_args()

    records = collect_records(args.manifest)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"_{args.label}-snapshot.json"
    out_path.write_text(json.dumps(records, indent=2))

    total_pages = sum(r["pages"] for r in records)
    total_dur = sum((r.get("duration_s") or 0) for r in records)
    weighted_conf = sum(r["mean_conf"]*r["pages"] for r in records) / max(1, total_pages)
    failures = sum(1 for r in records if r.get("status") == "failed")

    print(f"Snapshotted {len(records)} cards to {out_path}")
    print(f"  Total pages: {total_pages}")
    print(f"  Total wall-clock: {total_dur/60:.1f} min")
    print(f"  Page-weighted mean conf: {weighted_conf:.2f}")
    print(f"  Failures: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
