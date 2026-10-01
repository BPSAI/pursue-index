"""Key functions for the ``qc-coverage.json`` coverage spec.

Kept apart from :mod:`tests.support.payload_specs`, which registers the
spec, so the registry stays a list of declarations. The source paths live
here because both modules need them and this one is imported first.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pursue_index.clean.qc.coverage import build_coverage
from pursue_index.embed.image_observations import observation_text_for
from tests.support.payload_coverage import Key

MANIFEST = "data/manifests/latest.json"
PAGES = "web/public/data/pages.json"
IMAGE_OBSERVATIONS = "web/src/data/image-observations/index.json"
CLEAN_QC_BUNDLE = "web/public/data/clean-qc-bundle.json"
QC_COVERAGE = "web/public/data/qc-coverage.json"

#: Where the sidecars named by IMAGE_OBSERVATIONS live. They are read through
#: the site's own renderer rather than as declared sources, because the set of
#: files depends on the index; tests point this at a fixture directory.
OBSERVATIONS_DIR = Path(__file__).resolve().parents[2] / "web/src/data/image-observations"


def qc_keys(doc: Any) -> set[Key]:
    """Every fact the payload states, as comparable keys.

    One ``(card_id, status, asset_types)`` per card, asset types sorted (a
    card listed twice yields ``(card_id, "DUPLICATE", ())`` instead, which no
    source makes eligible); a partially judged card's judged and current page
    counts; each judged card's ``vision_text_pages``; every aggregate the page
    renders; and the provenance it was built from.
    """
    keys: set[Key] = set()
    seen: set[str] = set()
    for card in doc["cards"]:
        cid = card["card_id"]
        if cid in seen:
            keys.add((cid, "DUPLICATE", ()))
        else:
            keys.add((cid, card["status"], tuple(sorted(card["asset_types"]))))
        seen.add(cid)
        if "judged_pages" in card or "current_pages" in card:
            keys.add((cid, "page_counts", card.get("judged_pages"), card.get("current_pages")))
        if "vision_text_pages" in card:
            keys.add((cid, "vision_text_pages", tuple(card["vision_text_pages"])))
    keys.add(("total_cards", doc["total_cards"]))
    keys.update(("status_counts", status, n) for status, n in doc["status_counts"].items())
    keys.add(("unverified_other", tuple(doc["unverified_other"])))
    keys.add(("unverified_other_reasons", tuple(sorted(doc["unverified_other_reasons"].items()))))
    keys.add(("bundle_cards_not_in_manifest", tuple(doc["bundle_cards_not_in_manifest"])))
    vp = doc["vision_text_pages_in_judged_cards"]
    keys.add(("vision_text_pages_in_judged_cards", vp["cards"], vp["pages"]))
    src = doc["generated_from"]
    bundle = src["clean_qc_bundle"]
    keys.add(
        (
            "generated_from",
            src["manifest_csv_sha256"],
            src["manifest_fetched_at"],
            *(bundle[k] for k in sorted(bundle)),
        )
    )
    return keys


def eligible_qc_statuses(sources: Mapping[str, Any]) -> set[Key]:
    """The keys of a payload freshly built from the current sources."""
    index = sources[IMAGE_OBSERVATIONS]
    return qc_keys(
        build_coverage(
            sources[MANIFEST],
            sources[CLEAN_QC_BUNDLE],
            sources[PAGES],
            index,
            observation_text_for(index.get("card_ids", []), OBSERVATIONS_DIR),
        )
    )


def shipped_qc_statuses(doc: Any) -> set[Key]:
    """The keys of the payload as shipped."""
    return qc_keys(doc)
