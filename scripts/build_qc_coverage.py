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
import hashlib
import json

import build_asr_diff_bundle

from pursue_index import get_logger
from pursue_index.paths import repo_root

REPO_ROOT = repo_root()

from pursue_index.clean.qc.coverage import build_coverage
from pursue_index.clean.qc.staleness import card_page_shas
from pursue_index.embed.image_observations import observation_text_for
from pursue_index.release.chunked_asset import asset_exists, read_asset_bytes, read_asset_json

log = get_logger(__name__)

DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_BUNDLE = REPO_ROOT / "web" / "public" / "data" / "clean-qc-bundle.json"
DEFAULT_PAGES = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_PAGES_CLEANED = REPO_ROOT / "web" / "public" / "data" / "pages-cleaned.json"
DEFAULT_OBSERVATIONS = REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json"
DEFAULT_ASR_DIFF_BUNDLE = REPO_ROOT / "web" / "public" / "data" / "asr-diff-bundle.json"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "qc-coverage.json"


def _asr_diff_status(asr_diff_bundle_path: Path) -> dict[str, str]:
    """``{card_id: status}`` from the published asr-diff bundle, or ``{}``
    when absent -- no second-engine comparison has been published yet,
    which is the state of the repo until an operator runs one (R7C.27)."""
    if not asset_exists(asr_diff_bundle_path):
        return {}
    try:
        return build_asr_diff_bundle.as_status_map(read_asset_json(asr_diff_bundle_path))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Fails safe (cards revert to unverified_transcript) but never silently.
        log.warning("asr_diff.bundle.unreadable", path=str(asr_diff_bundle_path.name),
                    error=type(exc).__name__)
        return {}


def _page_shas(pages_cleaned_path: Path) -> dict[str, dict[int, str]]:
    """``{card_id: {page: source_page_sha256}}``, or ``{}`` if absent/unreadable.

    ``pages-cleaned.json`` is itself optional (an OCR-pipeline output, not
    every checkout rebuilds it). Its absence alone verifies nothing, which is
    fine for a legacy bundle with no digest field; ``_verification_gap``
    fails the gate closed when the bundle DOES carry digests.
    """
    try:
        if not asset_exists(pages_cleaned_path):
            return {}
        return card_page_shas(read_asset_json(pages_cleaned_path))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _provenance_gap(pages_cleaned_path: Path, pages_path: Path) -> str | None:
    """Why the cleaned asset cannot be tied to the current pages.json."""
    try:
        meta = read_asset_json(pages_cleaned_path).get("meta", {})
        recorded = meta.get("pages_json_sha256")
        current = hashlib.sha256(read_asset_bytes(pages_path)).hexdigest()
    except (OSError, ValueError, AttributeError, TypeError):
        return f"{pages_cleaned_path.name} provenance unavailable: cannot read it or {pages_path.name}"
    if not recorded:
        return (f"{pages_cleaned_path.name} provenance unavailable: no pages_json_sha256 "
                "(built before provenance was recorded; rebuild it)")
    if recorded != current:
        return f"cleaned asset stale: rebuilt from {recorded[:12]}, current {current[:12]}"
    return None


def _verification_gaps(
    bundle_path: Path, pages_cleaned_path: Path, statuses: dict[str, str],
    pages_path: Path,
) -> list[str]:
    """Why digests cannot be checked: one entry per problem, ``[]`` when fine.

    Fails closed per card as well as globally: a digest-bearing card whose
    committed shas are not one-per-judged-page reads as unverifiable here
    rather than silently classifying ``judged``. A legacy bundle (no digest
    on any card) has nothing to verify and yields ``[]``.
    """
    bundle = read_asset_json(bundle_path)
    cards = [c for c in bundle.get("cards", []) if c.get("judged_pages_digest")]
    if not cards:
        return []
    if not asset_exists(pages_cleaned_path):
        return [f"{pages_cleaned_path.name} is missing"]
    shas = _page_shas(pages_cleaned_path)
    if not shas:
        return [f"{pages_cleaned_path.name} is unreadable or carries no page shas"]
    if provenance := _provenance_gap(pages_cleaned_path, pages_path):
        return [provenance]
    return [
        f"{c['card_id']}: {len(shas.get(c['card_id'], {}))} page sha(s) for "
        f"{c.get('page_count')} judged page(s)"
        for c in cards
        # Only a card the classifier called judged was meant to be verified;
        # a partially judged one (page count changed) is legitimately skipped.
        if statuses.get(c["card_id"]) == "judged"
        and len(shas.get(c["card_id"], {})) != c.get("page_count")
    ]


def build(
    *,
    manifest_path: Path,
    bundle_path: Path,
    pages_path: Path,
    observations_path: Path,
    out_path: Path,
    pages_cleaned_path: Path | None = None,
    asr_diff_bundle_path: Path | None = None,
) -> dict:
    """Read the sources, write the coverage payload, return it."""
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    doc = build_coverage(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        read_asset_json(bundle_path),
        read_asset_json(pages_path),
        observations,
        # The same rendering the search payload uses; a missing or malformed
        # sidecar yields no text, so its card is not counted as described.
        observation_text_for(observations.get("card_ids", []), observations_path.parent),
        _page_shas(pages_cleaned_path) if pages_cleaned_path else {},
        _asr_diff_status(asr_diff_bundle_path) if asr_diff_bundle_path else {},
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
    parser.add_argument("--asr-diff-bundle", type=Path, default=DEFAULT_ASR_DIFF_BUNDLE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    doc = build(
        manifest_path=args.manifest,
        bundle_path=args.bundle,
        pages_path=args.pages,
        observations_path=args.observations,
        out_path=args.out,
        pages_cleaned_path=args.pages_cleaned,
        asr_diff_bundle_path=args.asr_diff_bundle,
    )
    gaps = _verification_gaps(
        args.bundle, args.pages_cleaned, {c["card_id"]: c["status"] for c in doc["cards"]},
        args.pages,
    )
    if gaps:
        for gap in gaps:
            print(f"qc-coverage: digest verification unavailable: {gap}")
        print(f"qc-coverage: {len(gaps)} digest verification gap(s) -- failing the gate")
        return 1
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
