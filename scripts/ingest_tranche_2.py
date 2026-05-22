#!/usr/bin/env python3
"""Ingest tranche-2 (war.gov release_02) into the pursue-index manifest.

Phase 1 of the tranche-2 ingest sequence. Synthesizes 6 net-new card
records and appends them to:

    1. data/manifests/latest.json      (pipeline source of truth)
    2. web/src/data/manifest.json      (Astro build input)

Canonical URL (operator-supplied 2026-05-22, after correction)
--------------------------------------------------------------
The 6 PDFs ship as a single ZIP at war.gov:

    https://www.war.gov/medialink/ufo/052226/release_02/release_02_document_bundle.zip

Per-card asset_url uses the bundle URL + filename fragment as a
faithful pointer to the zip member:

    https://www.war.gov/medialink/ufo/052226/release_02/release_02_document_bundle.zip#<original-filename>

The original filename (CamelCase, underscore-separated) is preserved in
the fragment — it matches the zip member exactly. Do NOT slugify it.

History note: an earlier (mistaken) attempt used the guessed pattern
`/medialink/ufo/release_2/<lowercase-with-dashes>.pdf`. That generated
the wrong card_ids and the wrong asset_urls. This script's CARD_SPECS
are recomputed from the canonical bundle URL.

card_id derivation matches the existing pipeline
(pursue_index.scrape.normalize.stable_card_id):

    card_id = sha256(asset_url_with_fragment)[:16]

We compute it here at import time so a typo in a filename surfaces
immediately rather than as a silent mismatch.

Notes
-----
- Tranche 2 has no upstream CSV. Cards are constructed by hand from
  the operator-provided bundle (pulled out-of-band; the 6 PDFs are
  visible in /home/david/Desktop/release_02_document_bundle/).
- The manifest is NOT alphabetically sorted (verified 2026-05-22
  against current `latest.json`), so appending preserves load order.
- Reruns are safe: cards whose card_id is already present are skipped.

Run
---
    cd /home/david/projects/pursue-index
    python3 scripts/ingest_tranche_2.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PIPELINE = REPO_ROOT / "data" / "manifests" / "latest.json"
MANIFEST_WEB = REPO_ROOT / "web" / "src" / "data" / "manifest.json"

BUNDLE_URL = (
    "https://www.war.gov/medialink/ufo/052226/release_02/"
    "release_02_document_bundle.zip"
)


def _asset_url_for(filename: str) -> str:
    """Return the canonical asset_url for a zip-member filename."""
    return f"{BUNDLE_URL}#{filename}"


def _card_id(asset_url: str) -> str:
    """Match pursue_index.scrape.normalize.stable_card_id derivation."""
    return hashlib.sha256(asset_url.encode("utf-8")).hexdigest()[:16]


# (title, agency, original CamelCase filename from the zip bundle)
_SPECS_INPUT: list[tuple[str, str, str]] = [
    (
        "ODNI-UAP-D001, USPER Narrative - Senior USIC, 2026",
        "Office of the Director of National Intelligence",
        "ODNI-UAP-D001_USPER_Narrative_Senior_USIC.pdf",
    ),
    (
        "CIA-UAP-D001, Intelligence Information Report - USSR, 1973",
        "Central Intelligence Agency",
        "CIA-UAP-D001_Intelligence_Information_Report_USSR_1973.pdf",
    ),
    (
        "DOE-UAP-D001, PANTEX Image, 2026",
        "Department of Energy",
        "DOE-UAP-D001_PANTEX_Image.pdf",
    ),
    (
        "DOE-UAP-D002, James Tuck Correspondence, undated",
        "Department of Energy",
        "DOE-UAP-D002_JamesTuck_Correspondence.pdf",
    ),
    (
        "DOE-UAP-D003, Pajarito Astronomers, undated",
        "Department of Energy",
        "DOE-UAP-D003_Pajarito_Astronomers.pdf",
    ),
    (
        "DOW-UAP-D017, General Correspondence of Sandia, 2026",
        "Department of War",
        "DOW-UAP-D017_General_Correspondence_Of_Sandia.pdf",
    ),
]

CARD_SPECS: list[dict[str, Any]] = []
for _title, _agency, _filename in _SPECS_INPUT:
    _url = _asset_url_for(_filename)
    CARD_SPECS.append(
        {
            "card_id": _card_id(_url),
            "title": _title,
            "agency": _agency,
            "asset_filename": _filename,
            "asset_url": _url,
        }
    )

DESCRIPTION = "Released in tranche 2 (2026-05-22). Operator editorial pending."
RELEASE_DATE = "5/22/26"


def build_card_record(spec: dict[str, Any]) -> dict[str, Any]:
    """Construct one 28-field card record matching the manifest schema."""
    return {
        "card_id": spec["card_id"],
        "title": spec["title"],
        "asset_type": "PDF",
        "agency": spec["agency"],
        "release_date": RELEASE_DATE,
        "incident_date": None,
        "incident_location": None,
        "redacted": False,
        "description": DESCRIPTION,
        "asset_url": spec["asset_url"],
        "asset_filename": spec["asset_filename"],
        "modal_image_url": None,
        "dvids_video_id": None,
        "video_title": None,
        "pdf_pairing": None,
        "video_pairing": None,
        "image_alt_text": None,
        "image_virin": None,
        "original_classification": None,
        "display_date": None,
        "display_date_range": None,
        "display_date_evidence": None,
        "display_date_evidence_card_ref": None,
        "display_date_curator": None,
        "display_date_approved_at": None,
        "display_date_abstention": None,
        "manifest_incident_date_raw": None,
        "raw": {},
    }


def merge_new_cards(manifest: dict[str, Any], specs: list[dict[str, Any]]) -> int:
    """Append any specs whose card_id isn't already present. Returns count added."""
    existing = {c["card_id"] for c in manifest["cards"]}
    added = 0
    for spec in specs:
        if spec["card_id"] in existing:
            print(f"  skip (already present): {spec['card_id']}", file=sys.stderr)
            continue
        manifest["cards"].append(build_card_record(spec))
        added += 1
    return added


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest with a trailing newline (matches existing format)."""
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> int:
    if not MANIFEST_PIPELINE.exists():
        print(f"ERROR: pipeline manifest not found at {MANIFEST_PIPELINE}", file=sys.stderr)
        return 1
    if not MANIFEST_WEB.exists():
        print(f"ERROR: web manifest not found at {MANIFEST_WEB}", file=sys.stderr)
        return 1

    print("Tranche-2 specs (corrected derivation):")
    for spec in CARD_SPECS:
        print(f"  {spec['card_id']}  {spec['asset_filename']}")

    pipeline = json.loads(MANIFEST_PIPELINE.read_text())
    web = json.loads(MANIFEST_WEB.read_text())

    before_pipeline = len(pipeline["cards"])
    before_web = len(web["cards"])
    print(f"Before: pipeline={before_pipeline} web={before_web}")

    if before_pipeline != before_web:
        print(
            f"WARNING: pipeline ({before_pipeline}) and web ({before_web}) manifest "
            "counts diverged before this script ran.",
            file=sys.stderr,
        )

    added_pipeline = merge_new_cards(pipeline, CARD_SPECS)
    added_web = merge_new_cards(web, CARD_SPECS)
    print(f"Added: pipeline=+{added_pipeline} web=+{added_web}")

    write_manifest(MANIFEST_PIPELINE, pipeline)
    write_manifest(MANIFEST_WEB, web)

    after_pipeline = len(pipeline["cards"])
    after_web = len(web["cards"])
    print(f"After: pipeline={after_pipeline} web={after_web}")

    if after_pipeline != after_web:
        print("ERROR: pipeline and web manifest counts diverged.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
