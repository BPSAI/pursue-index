"""Unit tests for the eligibility predicates of each derived payload.

Synthetic manifests and payloads only — these pin what each predicate
*means* (which entries are legitimately excluded, and in which
direction the assertion runs) without depending on the corpus's
current contents.
"""

from __future__ import annotations

from typing import Any

from tests.support.payload_coverage import evaluate
from tests.support.payload_specs import MANIFEST, PAGES, SPECS, spec_for

_MANIFEST = {
    "cards": [
        {"card_id": "vid1", "asset_type": "VID"},
        {"card_id": "vid1", "asset_type": "VID"},  # upstream repeats card_ids
        {"card_id": "aud1", "asset_type": "AUD"},
        {"card_id": "pdf1", "asset_type": "PDF"},
        {"card_id": "img1", "asset_type": "IMG"},
    ]
}

_PAGES = [
    {"card_id": "pdf1", "page": 1, "text": "hello"},
    {"card_id": "pdf1", "page": 2, "text": "   "},  # empty after strip
    {"card_id": "img1", "page": 1, "text": "caption"},
]


def _loader(payload_path: str, payload: Any):
    docs: dict[str, Any] = {
        MANIFEST: _MANIFEST,
        PAGES: _PAGES,
        payload_path: payload,
    }
    return lambda rel: docs[rel]


def _run(payload_path: str, payload: Any):
    spec = spec_for(payload_path)
    return evaluate(spec, _loader(payload_path, payload))


def test_every_declared_spec_is_unique_and_sources_are_repo_committed() -> None:
    """The gate must run in credential-free CI: committed files only."""
    paths = [spec.payload for spec in SPECS]
    assert len(paths) == len(set(paths))
    for spec in SPECS:
        assert spec.rationale
        for source in spec.sources:
            assert not source.startswith("/")
            assert source in {MANIFEST, PAGES}


def test_embed_index_is_keyed_by_pages_with_non_empty_text() -> None:
    """Whitespace-only pages are the one legitimate exclusion."""
    result = _run(
        "web/public/data/embed_index.json",
        {"pages": [["pdf1", 1], ["img1", 1]]},
    )

    assert result.ok
    assert result.eligible_count == 2


def test_embed_index_flags_a_stale_row_and_an_uncovered_page() -> None:
    result = _run(
        "web/public/data/embed_index.json",
        {"pages": [["pdf1", 1], ["gone", 7]]},
    )

    assert result.missing == [("img1", 1)]
    assert result.extra == [("gone", 7)]


def test_atlas_layout_shares_the_embed_predicate() -> None:
    result = _run(
        "web/public/data/atlas-layout.json",
        {"points": [{"card_id": "pdf1", "page": 1}]},
    )

    assert result.missing == [("img1", 1)]


def test_video_posters_cover_distinct_vid_and_aud_card_ids() -> None:
    """Repeated manifest rows count once; PDF/IMG cards are excluded."""
    result = _run(
        "web/public/data/video-posters/index.json",
        {"posters": {"vid1": "vid1.jpg", "aud1": "aud1.jpg"}},
    )

    assert result.ok
    assert result.eligible_count == 2


def test_video_posters_report_an_uncovered_audio_card() -> None:
    result = _run(
        "web/public/data/video-posters/index.json",
        {"posters": {"vid1": "vid1.jpg"}},
    )

    assert result.missing == ["aud1"]


def test_thumbs_cover_distinct_card_ids_carrying_a_pdf_row() -> None:
    result = _run("web/public/data/thumbs/index.json", {"thumbs": {}})

    assert result.missing == ["pdf1"]


def test_pages_json_is_gated_structurally_against_the_manifest() -> None:
    """OCR coverage is operational; CI only asserts no orphan card_ids."""
    payload = [
        {"card_id": "pdf1", "page": 1, "text": "hi"},
        {"card_id": "ghost", "page": 1, "text": "hi"},
    ]

    result = _run(PAGES, payload)

    assert result.extra == ["ghost"]
    assert result.missing == []  # img1/vid1 needing no OCR is not a CI failure
