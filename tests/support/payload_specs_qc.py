"""Key functions for the ``qc-coverage.json`` coverage spec.

Kept apart from :mod:`tests.support.payload_specs`, which registers the
spec, so the registry stays a list of declarations. The source paths live
here because both modules need them and this one is imported first.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pursue_index.clean.qc.coverage import classify_cards
from tests.support.payload_coverage import Key

MANIFEST = "data/manifests/latest.json"
PAGES = "web/public/data/pages.json"
IMAGE_OBSERVATIONS = "web/src/data/image-observations/index.json"
CLEAN_QC_BUNDLE = "web/public/data/clean-qc-bundle.json"
QC_COVERAGE = "web/public/data/qc-coverage.json"


def _provenance_key(csv_sha256: str, bundle_generated_at: str) -> Key:
    return ("generated_from", csv_sha256, bundle_generated_at)


def eligible_qc_statuses(sources: Mapping[str, Any]) -> set[Key]:
    """(card_id, status) for every distinct manifest card, plus the inputs'
    provenance, so a stale payload fails even when its card set still fits."""
    statuses = classify_cards(
        sources[MANIFEST], sources[CLEAN_QC_BUNDLE], sources[PAGES], sources[IMAGE_OBSERVATIONS]
    )
    keys: set[Key] = set(statuses.items())
    keys.add(
        _provenance_key(
            sources[MANIFEST]["csv_sha256"], sources[CLEAN_QC_BUNDLE]["generated_at"]
        )
    )
    return keys


def shipped_qc_statuses(doc: Any) -> set[Key]:
    """(card_id, status) as shipped. A card listed twice yields a
    ``(card_id, "DUPLICATE")`` key, which no source makes eligible."""
    keys: set[Key] = set()
    seen: set[str] = set()
    for card in doc["cards"]:
        cid = card["card_id"]
        keys.add((cid, "DUPLICATE") if cid in seen else (cid, card["status"]))
        seen.add(cid)
    src = doc["generated_from"]
    keys.add(_provenance_key(src["manifest_csv_sha256"], src["clean_qc_bundle"]["generated_at"]))
    return keys
