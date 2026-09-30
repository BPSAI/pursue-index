"""QC coverage status for every distinct manifest card.

The clean-QC bundle lists the cards the page-level judge covered and says
nothing about the rest, so an unverified card was absent rather than marked.
This module gives every distinct card_id in the manifest exactly one status:

* ``judged``                — the card is in the clean-QC bundle and the
                              bundle's ``page_count`` equals the card's
                              current page count (see below).
* ``partially_judged``      — in the bundle, but its page count has changed
                              since the sweep (e.g. a re-OCR added pages);
                              ``judged_pages`` / ``current_pages`` recorded.
* ``unverified_transcript`` — an AUD card with transcript text in pages.json.
* ``unverified_vision``     — an IMG card with a vision description (listed in
                              the image-observations index).
* ``no_text``               — no text of any kind in pages.json and no vision
                              description (most VID cards).
* ``unverified_other``      — anything else, e.g. a document with OCR text the
                              judge has not covered. Listed by id so nothing
                              hides.

Checked in that order, so a card with several asset rows (a PDF paired with
a video) takes the strongest status its sources support.

The bundle's ``page_count`` is the number of cleanup rows the judge graded
for the card (``pursue_index.clean.qc.runner.run_card`` grades every row of
the cleanup sidecar, one per OCR page, including pages the cleanup skipped as
empty input). The current count is therefore every distinct page row the
card has in pages.json, with or without text.

Judged cards can also hold image-only pages whose text is our own vision
description rather than OCR (see ``pursue_index.embed.image_observations``);
the cleanup pass skipped those pages as empty input, so the judge had no
cleaned text for them. They are named per card as ``vision_text_pages``.

Pure: callers pass parsed JSON. Output is sorted and carries no wall-clock
time beyond what the inputs record.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pursue_index.embed.image_observations import OBSERVATIONS_HEADER

SCHEMA_VERSION = 1

STATUSES: tuple[str, ...] = (
    "judged",
    "partially_judged",
    "unverified_transcript",
    "unverified_vision",
    "no_text",
    "unverified_other",
)


def _asset_types(manifest: Mapping[str, Any]) -> dict[str, set[str]]:
    types: dict[str, set[str]] = {}
    for row in manifest["cards"]:
        types.setdefault(row["card_id"], set()).add(row.get("asset_type") or "")
    return types


def _cards_with_text(pages: Iterable[Mapping[str, Any]]) -> set[str]:
    return {p["card_id"] for p in pages if (p.get("text") or "").strip()}


def _judged_ids(bundle: Mapping[str, Any]) -> set[str]:
    return {c["card_id"] for c in bundle["cards"]}


def _judged_page_counts(bundle: Mapping[str, Any]) -> dict[str, int]:
    return {c["card_id"]: int(c["page_count"]) for c in bundle["cards"]}


def _current_page_counts(pages: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Distinct page rows per card, text or not (the judge's eligibility)."""
    seen: dict[str, set[int]] = {}
    for p in pages:
        seen.setdefault(p["card_id"], set()).add(int(p["page"]))
    return {cid: len(pgs) for cid, pgs in seen.items()}


def classify_cards(
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
    pages: Iterable[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, str]:
    """``{card_id: status}`` for every distinct card_id in the manifest."""
    pages = list(pages)
    types = _asset_types(manifest)
    judged_pages = _judged_page_counts(bundle)
    current_pages = _current_page_counts(pages)
    with_text = _cards_with_text(pages)
    described = set(observations.get("card_ids", []))
    statuses: dict[str, str] = {}
    for card_id, kinds in types.items():
        if card_id in judged_pages:
            same = judged_pages[card_id] == current_pages.get(card_id, 0)
            status = "judged" if same else "partially_judged"
        elif "AUD" in kinds and card_id in with_text:
            status = "unverified_transcript"
        elif "IMG" in kinds and card_id in described:
            status = "unverified_vision"
        elif card_id not in with_text and card_id not in described:
            status = "no_text"
        else:
            status = "unverified_other"
        statuses[card_id] = status
    return statuses


def _vision_text_pages(pages: Iterable[Mapping[str, Any]], card_ids: set[str]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for p in pages:
        if p["card_id"] in card_ids and (p.get("text") or "").startswith(OBSERVATIONS_HEADER):
            found.setdefault(p["card_id"], []).append(int(p["page"]))
    return {cid: sorted(set(pgs)) for cid, pgs in found.items()}


def build_coverage(
    manifest: Mapping[str, Any],
    bundle: Mapping[str, Any],
    pages: Iterable[Mapping[str, Any]],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """The ``qc-coverage.json`` document."""
    pages = list(pages)
    types = _asset_types(manifest)
    # A card that left the corpus after the sweep: listed, never counted.
    stray = sorted(_judged_ids(bundle) - types.keys())
    statuses = classify_cards(manifest, bundle, pages, observations)
    judged = {cid for cid, s in statuses.items() if s in ("judged", "partially_judged")}
    vision_pages = _vision_text_pages(pages, judged)
    judged_pages = _judged_page_counts(bundle)
    current_pages = _current_page_counts(pages)

    cards: list[dict[str, Any]] = []
    for card_id in sorted(statuses):
        entry: dict[str, Any] = {
            "card_id": card_id,
            "asset_types": sorted(types[card_id]),
            "status": statuses[card_id],
        }
        if statuses[card_id] == "partially_judged":
            entry["judged_pages"] = judged_pages[card_id]
            entry["current_pages"] = current_pages.get(card_id, 0)
        if card_id in vision_pages:
            entry["vision_text_pages"] = vision_pages[card_id]
        cards.append(entry)

    counts = {s: 0 for s in STATUSES}
    for status in statuses.values():
        counts[status] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_from": {
            "manifest_csv_sha256": manifest["csv_sha256"],
            "manifest_fetched_at": manifest["fetched_at"],
            "clean_qc_bundle": {
                "bundle_schema_version": bundle["bundle_schema_version"],
                "generated_at": bundle["generated_at"],
                "runner_version": bundle["runner_version"],
                "judge_model": bundle["judge_model"],
            },
        },
        "total_cards": len(cards),
        "status_counts": counts,
        "unverified_other": sorted(c for c, s in statuses.items() if s == "unverified_other"),
        "bundle_cards_not_in_manifest": stray,
        "vision_text_pages_in_judged_cards": {
            "cards": len(vision_pages),
            "pages": sum(len(p) for p in vision_pages.values()),
        },
        "cards": cards,
    }
