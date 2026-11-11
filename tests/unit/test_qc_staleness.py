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


def test_card_page_shas_skips_and_names_malformed_rows() -> None:
    problems: list[str] = []
    doc = {"pages": [
        {"card_id": "c1", "page": 1, "source_page_sha256": "a" * 64},
        {"page": 2, "source_page_sha256": "b" * 64},
        "not a row",
        {"card_id": "c2", "page": None, "source_page_sha256": "c" * 64},
        {"card_id": "c3", "page": "2", "source_page_sha256": "d" * 64},
    ]}
    assert card_page_shas(doc, problems) == {"c1": {1: "a" * 64}, "c3": {2: "d" * 64}}
    assert problems == [
        "pages[1]: no card_id",
        "pages[2]: row is str, not an object",
        "pages[3]: c2: page None is not an integer",
    ]


def test_card_page_shas_without_a_problem_list_still_skips_bad_rows() -> None:
    assert card_page_shas({"pages": [{"page": 1}, {"card_id": "c", "page": 1,
                                                   "source_page_sha256": "e" * 64}]}) == {"c": {1: "e" * 64}}
