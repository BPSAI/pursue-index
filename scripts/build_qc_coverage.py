#!/usr/bin/env python3
"""Build ``web/public/data/qc-coverage.json``: a QC status for every card.

Reads the promoted manifest, the clean-QC bundle, pages.json (chunk-aware)
and the image-observations index, and writes one entry per distinct
card_id with its status (see ``pursue_index.clean.qc.coverage``). Committed
inputs only, so it runs anywhere the repo is checked out. Deterministic: a
rebuild over unchanged inputs is byte-identical.

Also reads ``pages-cleaned.json`` (chunk-aware) for each page's committed
``source_page_sha256`` and recomputes each judged card's digest against
the bundle's ``judged_pages_digest`` (R7C.15). A mismatch is a ``stale``
card -- a re-OCR or re-clean that changed page CONTENTS without changing
the page COUNT -- and this script's exit code fails the gate when any
card is stale. A bundle published before R7C.15 (no digest field) prints
a one-line backward-compatibility notice instead and classifies as
before.

Usage::

    python scripts/build_qc_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json

from pursue_index.paths import repo_root

REPO_ROOT = repo_root()

from pursue_index.clean.qc.coverage import build_coverage
from pursue_index.clean.qc.staleness import card_page_shas
from pursue_index.embed.image_observations import observation_text_for
from pursue_index.release.chunked_asset import asset_exists, read_asset_json

DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_BUNDLE = REPO_ROOT / "web" / "public" / "data" / "clean-qc-bundle.json"
DEFAULT_PAGES = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_PAGES_CLEANED = REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"
DEFAULT_OBSERVATIONS = REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "qc-coverage.json"


def _page_shas(pages_cleaned_path: Path) -> dict[str, dict[int, str]]:
    """``{card_id: {page: source_page_sha256}}``, or ``{}`` if absent.

    ``pages-cleaned.json`` is itself optional (an OCR-pipeline output, not
    every checkout rebuilds it) — its absence just means no card can be
    verified as stale, the same as a legacy bundle with no digest field.
    """
    if not asset_exists(pages_cleaned_path):
        return {}
    return card_page_shas(read_asset_json(pages_cleaned_path))


def build(
    *,
    manifest_path: Path,
    bundle_path: Path,
    pages_path: Path,
    observations_path: Path,
    out_path: Path,
    pages_cleaned_path: Path | None = None,
) -> dict:
    """Read the sources, write the coverage payload, return it."""
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    doc = build_coverage(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        json.loads(bundle_path.read_text(encoding="utf-8")),
        read_asset_json(pages_path),
        observations,
        # The same rendering the search payload uses; a missing or malformed
        # sidecar yields no text, so its card is not counted as described.
        observation_text_for(observations.get("card_ids", []), observations_path.parent),
        _page_shas(pages_cleaned_path) if pages_cleaned_path else {},
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--pages-cleaned", type=Path, default=DEFAULT_PAGES_CLEANED)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    doc = build(
        manifest_path=args.manifest,
        bundle_path=args.bundle,
        pages_path=args.pages,
        observations_path=args.observations,
        out_path=args.out,
        pages_cleaned_path=args.pages_cleaned,
    )
    counts = ", ".join(f"{k} {v}" for k, v in doc["status_counts"].items())
    print(f"qc-coverage: {doc['total_cards']} cards ({counts}) → {args.out}")
    if doc["unverified_other"]:
        for card_id, reason in doc["unverified_other_reasons"].items():
            print(f"qc-coverage: unverified_other {card_id}: {reason}")
    if doc["bundle_missing_digests"]:
        print(
            "qc-coverage: clean-qc bundle has no judged_pages_digest field "
            "(pre-R7C.15) -- staleness check skipped, judged cards verified "
            "by page_count only."
        )
    stale_ids = sorted(c["card_id"] for c in doc["cards"] if c["status"] == "stale")
    if stale_ids:
        for card_id in stale_ids:
            print(f"qc-coverage: stale {card_id}: page content changed since the sweep")
        print(f"qc-coverage: {len(stale_ids)} stale card(s) -- failing the gate")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
