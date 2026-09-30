#!/usr/bin/env python3
"""Build ``web/public/data/qc-coverage.json``: a QC status for every card.

Reads the promoted manifest, the clean-QC bundle, pages.json (chunk-aware)
and the image-observations index, and writes one entry per distinct
card_id with its status (see ``pursue_index.clean.qc.coverage``). Committed
inputs only, so it runs anywhere the repo is checked out. Deterministic: a
rebuild over unchanged inputs is byte-identical.

Usage::

    python scripts/build_qc_coverage.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.clean.qc.coverage import build_coverage  # noqa: E402
from pursue_index.release.chunked_asset import read_asset_json  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_BUNDLE = REPO_ROOT / "web" / "public" / "data" / "clean-qc-bundle.json"
DEFAULT_PAGES = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_OBSERVATIONS = REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "qc-coverage.json"


def build(
    *,
    manifest_path: Path,
    bundle_path: Path,
    pages_path: Path,
    observations_path: Path,
    out_path: Path,
) -> dict:
    """Read the sources, write the coverage payload, return it."""
    doc = build_coverage(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        json.loads(bundle_path.read_text(encoding="utf-8")),
        read_asset_json(pages_path),
        json.loads(observations_path.read_text(encoding="utf-8")),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    doc = build(
        manifest_path=args.manifest,
        bundle_path=args.bundle,
        pages_path=args.pages,
        observations_path=args.observations,
        out_path=args.out,
    )
    counts = ", ".join(f"{k} {v}" for k, v in doc["status_counts"].items())
    print(f"qc-coverage: {doc['total_cards']} cards ({counts}) → {args.out}")
    if doc["unverified_other"]:
        print(f"qc-coverage: unverified_other: {', '.join(doc['unverified_other'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
