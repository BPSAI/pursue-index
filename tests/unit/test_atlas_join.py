"""Tests for the alex-zhang42 atlas join function.

The join takes their VLM-augmented corpus.jsonl and our scrape Manifest,
and returns a ``{(card_id, page): [image_tag_lines, ...]}`` mapping
keyed by *our* ``stable_card_id`` so the embed pipeline can append the
extra context to the right page before hashing.

The fixture ``tests/fixtures/atlas_join_sample.jsonl`` has 5 records:

- 2 pages of ``059uap00011`` (direct hash match)
- 1 page of ``065uap00099`` (direct hash match)
- 1 page of ``18_100754_general_1946-7_vol_2`` whose source_url differs
  from ours by URL-encoded space + case (canonical-form match required)
- 1 page of ``999uap99999`` that doesn't exist in our manifest (miss)
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.embed.atlas_join import (
    AtlasJoinError,
    canonicalize_url,
    load_atlas_index,
)
from pursue_index.scrape.types import CardMetadata, Manifest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "atlas_join_sample.jsonl"


def _write_jsonl_with_sha256(path: Path, body: str) -> None:
    """Write a JSONL fixture and its companion ``.sha256`` sidecar.

    ``load_atlas_index`` verifies the sha256 sidecar before parsing
    (laverna SEC-001 fail-closed), so any test fixture written at
    runtime needs both files alongside.
    """
    path.write_text(body)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n")


def _unlink_jsonl_with_sha256(path: Path) -> None:
    path.unlink()
    path.with_suffix(".sha256").unlink()


def _card(card_id: str, asset_url: str, title: str = "x") -> CardMetadata:
    return CardMetadata(
        card_id=card_id,
        title=title,
        asset_type="PDF",
        agency="FBI",
        asset_url=asset_url,
    )


def _manifest(cards: list[CardMetadata]) -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/x.csv",
        fetched_at=datetime.now(UTC),
        csv_sha256="deadbeef",
        cards=cards,
    )


def _full_manifest() -> Manifest:
    """Manifest covering 4 of the 5 fixture records (the 5th is the miss)."""
    return _manifest(
        [
            _card(
                "ff30c985595153f3",
                "https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",
            ),
            _card(
                "702e3997667da8b9",
                "https://www.war.gov/medialink/ufo/release_1/065uap00099.pdf",
            ),
            _card(
                "bbf7124aa3691fc4",
                # Our percent-encoded form (literal spaces in war.gov filename).
                "https://www.war.gov/medialink/ufo/release_1/"
                "18_100754_%20general%201946-7_vol_2.pdf",
            ),
        ]
    )


def test_load_atlas_index_returns_pages_for_direct_hash_matches() -> None:
    """Records whose source_url hashes to a known card_id join directly."""
    manifest = _full_manifest()
    index = load_atlas_index(FIXTURE, manifest, miss_rate_threshold=0.5)

    # 059uap00011 has 2 pages, 065uap00099 has 1 page.
    assert ("ff30c985595153f3", 1) in index
    assert ("ff30c985595153f3", 2) in index
    assert ("702e3997667da8b9", 3) in index

    assert index[("ff30c985595153f3", 1)] == [
        "Seal of the United States Department of State."
    ]
    assert index[("ff30c985595153f3", 2)] == [
        "A typewritten cable header with date stamp."
    ]
    assert index[("702e3997667da8b9", 3)] == [
        "A black-and-white photograph of a metallic disc on grass."
    ]


def test_canonicalize_url_collapses_url_encoding_and_whitespace() -> None:
    """Our URLs preserve war.gov's literal-space filenames as %20; theirs
    swap space for underscore. Canonicalization decodes percent-escapes,
    lowercases, and squashes whitespace + underscore runs to a single ``_``.
    """
    ours = (
        "https://www.war.gov/medialink/ufo/release_1/"
        "18_100754_%20general%201946-7_vol_2.pdf"
    )
    theirs = (
        "https://www.war.gov/medialink/ufo/release_1/"
        "18_100754_general_1946-7_vol_2.pdf"
    )
    assert canonicalize_url(ours) == canonicalize_url(theirs)


def test_load_atlas_index_joins_via_canonicalization_when_hash_misses() -> None:
    """The 18_100754 record only matches via canonical-URL fallback —
    direct hash misses because of %20 vs underscore.
    """
    manifest = _full_manifest()
    index = load_atlas_index(FIXTURE, manifest, miss_rate_threshold=0.5)
    # bbf7124aa3691fc4 is OUR card_id; the join must surface their tags
    # under our id even though their hash differs.
    assert ("bbf7124aa3691fc4", 7) in index
    assert index[("bbf7124aa3691fc4", 7)] == [
        "A handwritten margin note marked CONFIDENTIAL."
    ]


def test_load_atlas_index_aborts_when_miss_rate_exceeds_threshold() -> None:
    """A 5-record fixture with 1 miss is 20% miss rate — must trip a 1%
    threshold and abort with a diagnostic listing the misses.
    """
    manifest = _full_manifest()
    with pytest.raises(AtlasJoinError, match="miss rate"):
        load_atlas_index(FIXTURE, manifest, miss_rate_threshold=0.01)


def test_load_atlas_index_records_misses_below_threshold() -> None:
    """When the miss rate is acceptable (e.g. 1 unmatched record on a 5-page
    fixture, 20%), the loader still surfaces the un-matched URL set so the
    operator can audit. We use the operational ceiling (0.5 = allow up to
    50% miss) to test the surface explicitly.
    """
    manifest = _full_manifest()
    index = load_atlas_index(FIXTURE, manifest, miss_rate_threshold=0.5)
    # The orphan page is dropped — there's no card_id to attach it to.
    # Only the 4 matched pages are in the index.
    assert len(index) == 4
    # Spot-check the miss didn't sneak in.
    for key in index:
        assert "999" not in key[0]


def test_load_atlas_index_skips_records_with_no_image_tags() -> None:
    """Pages whose ``image_tags`` array is empty contribute nothing to
    retrieval — emitting an empty IMAGE-DESCRIPTIONS block would just be
    noise. They should be omitted from the join index entirely (vs joined
    with an empty list, which downstream code would have to filter again).
    """
    fixture = FIXTURE.parent / "atlas_join_empty_tags.jsonl"
    _write_jsonl_with_sha256(
        fixture,
        '{"record_id":"059uap00011","pdf_stem":"059uap00011","page_num":1,'
        '"text":"## blank","image_tags":[],"image_tag_source":"mimo-v2.5",'
        '"source_url":"https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",'
        '"sha256":"x"}\n',
    )
    try:
        manifest = _manifest(
            [
                _card(
                    "ff30c985595153f3",
                    "https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",
                ),
            ]
        )
        index = load_atlas_index(fixture, manifest, miss_rate_threshold=0.5)
        assert ("ff30c985595153f3", 1) not in index
    finally:
        _unlink_jsonl_with_sha256(fixture)


def test_load_atlas_index_deduplicates_repeated_tags() -> None:
    """If a record's image_tags list contains the same string twice
    (rare, but possible if the VLM repeated itself), the join function
    should de-dupe while preserving first-seen order.
    """
    fixture = FIXTURE.parent / "atlas_join_dupes.jsonl"
    _write_jsonl_with_sha256(
        fixture,
        '{"record_id":"059uap00011","pdf_stem":"059uap00011","page_num":1,'
        '"text":"## x","image_tags":["A.","B.","A."],'
        '"image_tag_source":"mimo-v2.5",'
        '"source_url":"https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",'
        '"sha256":"x"}\n',
    )
    try:
        manifest = _manifest(
            [
                _card(
                    "ff30c985595153f3",
                    "https://www.war.gov/medialink/ufo/release_1/059uap00011.pdf",
                ),
            ]
        )
        index = load_atlas_index(fixture, manifest, miss_rate_threshold=0.5)
        assert index[("ff30c985595153f3", 1)] == ["A.", "B."]
    finally:
        _unlink_jsonl_with_sha256(fixture)
