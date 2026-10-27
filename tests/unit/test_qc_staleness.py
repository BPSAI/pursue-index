"""``pursue_index.clean.qc.staleness`` (R7C.15): the digest-vs-sidecar check.

Pure-function tests; the end-to-end classification (``judged`` vs
``stale`` surfaced through ``build_coverage``) lives in
``test_qc_coverage.py``.
"""

from __future__ import annotations

from pursue_index.clean.qc.staleness import card_page_shas, is_stale
from pursue_index.vendor.judged_pages_digest import judged_pages_digest


def test_is_stale_false_when_digest_matches() -> None:
    shas = {1: "a" * 64, 2: "b" * 64}
    digest = judged_pages_digest(shas.items())
    assert is_stale(digest, 2, shas) is False


def test_is_stale_true_when_digest_mismatches() -> None:
    shas = {1: "a" * 64, 2: "c" * 64}
    stale_digest = judged_pages_digest({1: "a" * 64, 2: "b" * 64}.items())
    assert is_stale(stale_digest, 2, shas) is True


def test_is_stale_false_when_bundle_card_carries_no_digest() -> None:
    """Legacy bundle (no digest field) -- unverifiable, not stale."""
    assert is_stale(None, 2, {1: "a" * 64, 2: "b" * 64}) is False


def test_is_stale_false_when_page_shas_are_incomplete() -> None:
    """A committed pages-cleaned.json missing a sha for one of the card's
    current pages cannot be verified -- unverifiable, not stale."""
    digest = judged_pages_digest({1: "a" * 64, 2: "b" * 64}.items())
    assert is_stale(digest, 2, {1: "a" * 64}) is False


def test_card_page_shas_omits_rows_without_a_sha() -> None:
    pages_cleaned = {
        "pages": [
            {"card_id": "c1", "page": 1, "source_page_sha256": "a" * 64},
            {"card_id": "c1", "page": 2, "source_page_sha256": ""},
            {"card_id": "c2", "page": 1},
        ]
    }
    assert card_page_shas(pages_cleaned) == {"c1": {1: "a" * 64}}
