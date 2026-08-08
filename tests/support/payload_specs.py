"""Eligibility predicates for every derived payload the site ships.

This is the single readable place where "what should this artifact
contain?" is written down, so exclusions are reviewable rather than
implied by whichever builder happened to run last. Each spec names its
sources, its key set on both sides, and the direction of the assertion.

Two properties are load-bearing:

* **Committed sources only.** Predicates read ``data/manifests/latest.json``
  and ``web/public/data/pages.json`` — both tracked in the repo — so the
  gate runs in credential-free CI with no NAS mount, no network, no env.
* **The manifest is never deduped.** Upstream legitimately repeats
  card_ids across rows (a card can appear with several asset rows). The
  predicates count DISTINCT card_ids for the payload's key set; the
  manifest itself is read as-is.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from tests.support.payload_coverage import Key, PayloadSpec

MANIFEST = "data/manifests/latest.json"
PAGES = "web/public/data/pages.json"

EMBED_INDEX = "web/public/data/embed_index.json"
ATLAS_LAYOUT = "web/public/data/atlas-layout.json"
VIDEO_POSTERS = "web/public/data/video-posters/index.json"
THUMBS = "web/public/data/thumbs/index.json"

#: Asset types whose cards get a poster frame.
AV_ASSET_TYPES = ("VID", "AUD")

_TEXT_KEYED_RATIONALE = (
    "every (card_id, page) in pages.json whose text is non-empty after "
    "strip(); pages with no extracted text are excluded, and nothing else is"
)


def _distinct_manifest_card_ids(manifest: Any, asset_types: Iterable[str]) -> set[Key]:
    """Distinct card_ids carrying at least one row of the given asset types."""
    wanted = set(asset_types)
    return {c["card_id"] for c in manifest["cards"] if c.get("asset_type") in wanted}


def _eligible_text_pages(sources: Mapping[str, Any]) -> set[Key]:
    return {
        (p["card_id"], p["page"])
        for p in sources[PAGES]
        if (p.get("text") or "").strip()
    }


def _eligible_av_cards(sources: Mapping[str, Any]) -> set[Key]:
    return _distinct_manifest_card_ids(sources[MANIFEST], AV_ASSET_TYPES)


def _eligible_pdf_cards(sources: Mapping[str, Any]) -> set[Key]:
    return _distinct_manifest_card_ids(sources[MANIFEST], ("PDF",))


def _eligible_manifest_cards(sources: Mapping[str, Any]) -> set[Key]:
    return {c["card_id"] for c in sources[MANIFEST]["cards"]}


def _shipped_embed_rows(doc: Any) -> set[Key]:
    return {(card_id, page) for card_id, page in doc["pages"]}


def _shipped_atlas_points(doc: Any) -> set[Key]:
    return {(p["card_id"], p["page"]) for p in doc["points"]}


def _shipped_poster_cards(doc: Any) -> set[Key]:
    return set(doc["posters"])


def _shipped_thumb_cards(doc: Any) -> set[Key]:
    return set(doc["thumbs"])


def _shipped_page_cards(doc: Any) -> set[Key]:
    return {p["card_id"] for p in doc}


SPECS: tuple[PayloadSpec, ...] = (
    # Search/atlas vectors. Key-set EQUALITY: a page with text and no
    # embedding is unsearchable, and an embedding for a page that is gone
    # (or whose text was cleared) is a stale row surfacing dead results.
    PayloadSpec(
        payload=EMBED_INDEX,
        sources=(PAGES,),
        eligible=_eligible_text_pages,
        shipped=_shipped_embed_rows,
        require_no_missing=True,
        require_no_extra=True,
        key_label="(card_id, page)",
        rationale=_TEXT_KEYED_RATIONALE,
    ),
    # Atlas coordinates are plotted from the same vectors, so they carry
    # the same predicate; a divergence between the two means one of the
    # builders ran and the other did not.
    PayloadSpec(
        payload=ATLAS_LAYOUT,
        sources=(PAGES,),
        eligible=_eligible_text_pages,
        shipped=_shipped_atlas_points,
        require_no_missing=True,
        require_no_extra=True,
        key_label="(card_id, page)",
        rationale=_TEXT_KEYED_RATIONALE,
    ),
    # Poster frames for the A/V tiles. Coverage only: a poster for a card
    # that has left the corpus is dead weight, not a broken surface, and
    # the tile grid never asks for it.
    PayloadSpec(
        payload=VIDEO_POSTERS,
        sources=(MANIFEST,),
        eligible=_eligible_av_cards,
        shipped=_shipped_poster_cards,
        require_no_missing=True,
        require_no_extra=False,
        key_label="card_id",
        rationale=(
            "every DISTINCT card_id in the manifest carrying at least one "
            "VID or AUD row; PDF- and IMG-only cards are excluded"
        ),
    ),
    # Document thumbnails. Coverage only, same reasoning as posters.
    PayloadSpec(
        payload=THUMBS,
        sources=(MANIFEST,),
        eligible=_eligible_pdf_cards,
        shipped=_shipped_thumb_cards,
        require_no_missing=True,
        require_no_extra=False,
        key_label="card_id",
        rationale=(
            "every DISTINCT card_id in the manifest carrying at least one "
            "PDF row; VID/AUD/IMG-only cards are excluded"
        ),
    ),
    # pages.json is OCR-derived: how much of the corpus has text is an
    # operational question (OCR spend, NAS access) that credential-free
    # CI cannot answer. So this spec is structural only — it asserts the
    # file has no card_id the manifest does not know about, and says
    # nothing about which cards are still un-OCR'd.
    PayloadSpec(
        payload=PAGES,
        sources=(MANIFEST,),
        eligible=_eligible_manifest_cards,
        shipped=_shipped_page_cards,
        require_no_missing=False,
        require_no_extra=True,
        key_label="card_id",
        rationale=(
            "structural sanity only: every card_id present in pages.json "
            "must exist in the manifest (OCR coverage is gated operationally)"
        ),
    ),
)


def spec_for(payload: str) -> PayloadSpec:
    """Look up a declared spec by its repo-relative payload path."""
    for spec in SPECS:
        if spec.payload == payload:
            return spec
    raise KeyError(f"no coverage spec declared for {payload}")
