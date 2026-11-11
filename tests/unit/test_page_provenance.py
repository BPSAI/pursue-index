"""Per-page provenance helpers shared by the cleaned-asset builder and the
coverage gate."""

from __future__ import annotations

from pursue_index.clean.prompt import input_sha256
from pursue_index.clean.qc.page_provenance import (
    ocr_page_shas,
    provenance_gaps,
    stamp_page_provenance,
    text_sha256,
    text_shas_by_page,
)


def test_text_hash_is_the_cleanup_runners_input_hash() -> None:
    for text in ("", "plain", "Résumé — 中文\r\n"):
        assert text_sha256(text) == input_sha256(text)
    assert text_sha256(None) == input_sha256("")


def test_stamp_and_check_round_trip() -> None:
    ocr = ocr_page_shas([{"page": 1, "text": "raw one"}, {"page": "2", "text": "raw two"}])
    pages_json = text_shas_by_page([{"card_id": "c", "page": 1, "text": "pub one"},
                                    {"card_id": "c", "page": 2, "text": "pub two"},
                                    {"page": 3}, "junk"])
    rows = [{"card_id": "c", "page": 1, "input_sha256": input_sha256("raw one")},
            {"card_id": "c", "page": 2, "input_sha256": input_sha256("raw two")}]
    stamped = stamp_page_provenance(rows, ocr, pages_json, "c")
    assert provenance_gaps(stamped, pages_json, {"c"}) == []
    changed = text_shas_by_page([{"card_id": "c", "page": 1, "text": "pub one"},
                                 {"card_id": "c", "page": 2, "text": "re-OCR'd"}])
    [gap] = provenance_gaps(stamped, changed, {"c"})
    assert gap.startswith("c page 2: pages.json text changed")


def test_a_page_with_no_ocr_row_is_untied() -> None:
    stamped = stamp_page_provenance([{"card_id": "c", "page": 4, "input_sha256": "a" * 64}],
                                    {}, {}, "c")
    assert stamped[0]["ocr_page_sha256"] == "" and stamped[0]["pages_json_text_sha256"] == ""
    [gap] = provenance_gaps(stamped, {}, {"c"})
    assert "no per-page provenance" in gap


def test_only_the_named_cards_are_checked() -> None:
    assert provenance_gaps([{"card_id": "other", "page": 1}], {}, {"c"}) == []
