"""The actionable tranche-ready surface appended to the poll alert.

The Release-4 gap was not detection (that fired in 90s) but that the alert only
carried verdict+counts — not the work-list, cost, or the command to run. This
builder produces the missing actionable block, credential-free.
"""

from __future__ import annotations

from pursue_index.release.ship import (
    OPERATED_STAGE_SEQUENCE,
    build_tranche_ready_summary,
)


def _summary(**over):
    kw = dict(
        tranche="13e730c18d6ea586bcb9b58984481b093f3e4802c33b0f9281258ee786f8abd1",
        verdict="needs-review",
        added=40,
        removed=0,
        field_changes=12,
        new_columns=0,
        scoped_count=14,
    )
    kw.update(over)
    return build_tranche_ready_summary(**kw)


def test_summary_has_verdict_counts_and_worklist():
    s = _summary()
    assert "needs-review" in s
    assert "40" in s and "12" in s  # added + field-only counts
    assert "14" in s  # scoped work-list size


def test_summary_has_cost_estimate():
    s = _summary()
    assert "$" in s  # est OCR+embed cost surfaced


def test_summary_has_copy_paste_ship_command_with_sha():
    s = _summary()
    assert "/ship-tranche 13e730c18d6ea586" in s  # ready-to-run, sha included


def test_summary_metadata_only_tranche_notes_no_ingest():
    s = _summary(added=0, field_changes=1, scoped_count=0)
    # a field-only/metadata tranche has nothing to OCR/embed — say so
    assert "0" in s
    low = s.lower()
    assert "metadata" in low or "no " in low


def test_summary_lists_scoped_worklist_card_ids_when_given():
    """The operator should see WHICH cards, not only how many (the worklist)."""
    ids = [f"card{i:02d}" for i in range(3)]
    s = _summary(scoped_count=3, scoped_ids=ids)
    for cid in ids:
        assert cid in s


def _stage_position(name: str) -> int:
    """Where a stage sits in the operated sequence, matched on its leading word."""
    for i, stage in enumerate(OPERATED_STAGE_SEQUENCE):
        if stage.split()[0].lower() == name:
            return i
    raise AssertionError(f"{name!r} is not in the operated stage sequence")


def test_operated_sequence_runs_approve_through_ship_ready():
    """The tranche contract begins at approve and ends at ship-ready."""
    assert _stage_position("approve") == 0
    assert OPERATED_STAGE_SEQUENCE[-1] == "ship-ready"


def test_vision_runs_after_ocr_and_before_embed():
    """Vision is an operator-attended spend stage that feeds the embed payload.

    It reads page images, so it follows OCR; the embed payload carries its
    observations alongside page text, so it precedes embed.
    """
    assert _stage_position("ocr") < _stage_position("vision") < _stage_position("embed")


def test_summary_names_every_operated_stage_in_order():
    """The operator-facing block spells out the whole sequence, in sequence."""
    block = _summary().split("**Run the operated release**", 1)[1]
    positions = [block.index(stage) for stage in OPERATED_STAGE_SEQUENCE]
    assert positions == sorted(positions)


def test_summary_caps_worklist_and_notes_remainder():
    ids = [f"card{i:02d}" for i in range(40)]
    s = _summary(scoped_count=40, scoped_ids=ids)
    # First few are shown; an overflow-count note appears rather than 40 lines.
    assert "card00" in s
    assert "more" in s.lower()


# --- R7C.5: the per-page estimate ------------------------------------------


def test_summary_with_page_counts_prices_pages_not_cards():
    s = _summary(scoped_count=3, scoped_ids=["a", "b", "c"],
                 page_counts={"a": 1, "b": 10, "c": 100}, fallback_card_ids=[])
    assert "111 pages" in s
    assert "recommended cap" in s
    assert "table estimate" in s
    assert "partial" not in s.lower()


def test_summary_names_cards_whose_fetch_failed_and_marks_partial():
    s = _summary(scoped_count=3, scoped_ids=["a", "b", "c"],
                 page_counts={"a": 1, "b": 10}, fallback_card_ids=["c"])
    assert "partial" in s.lower()
    assert "`c`" in s.split("partial", 1)[1]


def test_summary_without_page_counts_is_a_partial_per_card_estimate():
    s = _summary(scoped_count=2, scoped_ids=["a", "b"])
    assert "partial" in s.lower()
    assert "40 pages" in s  # 2 cards x 20-page per-card fallback


def test_scoped_cards_with_no_count_and_no_fetch_are_priced_as_fallbacks():
    """An IMG card never reaches the PDF fetch, but ingest OCRs it: price it."""
    s = _summary(scoped_count=2, scoped_ids=["a", "img"],
                 page_counts={"a": 10}, fallback_card_ids=[])
    assert "30 pages" in s  # 10 counted + 1 uncounted card x 20-page fallback
    assert "partial" in s.lower()
    assert "`img`" in s.split("partial", 1)[1]


def test_an_all_image_tranche_is_not_priced_at_zero():
    s = _summary(scoped_count=3, scoped_ids=["x", "y", "z"], page_counts={}, fallback_card_ids=[])
    assert "$0.00 low" not in s
    assert "60 pages" in s


def test_uncounted_cards_without_ids_still_fall_back():
    s = _summary(scoped_count=3, scoped_ids=None, page_counts={"a": 5}, fallback_card_ids=[])
    assert "45 pages" in s  # 5 counted + 2 unnamed cards x 20


def test_ids_that_could_break_a_markdown_code_span_are_not_rendered():
    evil = "ab`\n# injected"
    s = _summary(scoped_count=2, scoped_ids=["ok", evil], page_counts=None)
    assert "injected" not in s
    assert "`ok`" in s


def test_av_cards_are_not_priced_as_ocr_work():
    s = _summary(scoped_count=3, scoped_ids=["a", "clip", "song"],
                 page_counts={"a": 10}, fallback_card_ids=[], av_card_ids=["clip", "song"])
    assert "10 pages" in s
    assert "partial" not in s.lower()
