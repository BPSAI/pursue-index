"""Per-page provenance helpers shared by the cleaned-asset builder, the
search-payload builder and the coverage gate."""

from __future__ import annotations

import sys
from pathlib import Path

from pursue_index.clean.prompt import input_sha256
from pursue_index.clean.qc.page_provenance import (
    ocr_page_provenance,
    provenance_gaps,
    published_ocr_text,
    published_pages,
    stamp_page_provenance,
    text_sha256,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import _search_pages  # type: ignore[import-not-found]


def test_text_hash_is_the_cleanup_runners_input_hash() -> None:
    for text in ("", "plain", "Résumé — 中文\r\n"):
        assert text_sha256(text) == input_sha256(text)
    assert text_sha256(None) == input_sha256("")


def test_the_search_payload_publishes_ocr_text_through_the_same_transform() -> None:
    raw = "<b>Bold</b> and <u>under</u> <i>it</i> <table>kept</table>"
    assert published_ocr_text(raw) == "Bold and under it <table>kept</table>"
    assert _search_pages._resolve_page_text("c", 1, raw, None) == published_ocr_text(raw)


def _published(*rows: tuple[str, int, str]) -> dict:
    return published_pages([{"card_id": c, "page": p, "text": t} for c, p, t in rows])


def test_stamp_and_check_round_trip() -> None:
    ocr = ocr_page_provenance([{"page": 1, "text": "<b>raw</b> one"}, {"page": "2", "text": "raw two"}])
    rows = [{"card_id": "c", "page": 1, "input_sha256": input_sha256("<b>raw</b> one")},
            {"card_id": "c", "page": 2, "input_sha256": input_sha256("raw two")}]
    stamped = stamp_page_provenance(rows, ocr)
    assert provenance_gaps(stamped, _published(("c", 1, "raw one"), ("c", 2, "raw two")), {"c"}) == []
    [gap] = provenance_gaps(stamped, _published(("c", 1, "raw one"), ("c", 2, "old two")), {"c"})
    assert gap.startswith("c page 2: pages.json does not publish the OCR text")
    [gap] = provenance_gaps(stamped, _published(("c", 1, "raw one")), {"c"})
    assert gap == "c page 2: not in pages.json"


def test_published_pages_ignores_malformed_rows() -> None:
    assert published_pages([{"page": 3}, "junk", {"card_id": "c", "page": "x"}]) == {}
    assert published_pages("not a list") == {}


def test_a_page_with_no_ocr_row_is_untied() -> None:
    stamped = stamp_page_provenance([{"card_id": "c", "page": 4, "input_sha256": "a" * 64}], {})
    assert stamped[0]["ocr_page_sha256"] == "" and stamped[0]["ocr_published_sha256"] == ""
    [gap] = provenance_gaps(stamped, {}, {"c"})
    assert "no per-page provenance" in gap


def test_only_the_named_cards_are_checked() -> None:
    assert provenance_gaps([{"card_id": "other", "page": 1}], {}, {"c"}) == []
