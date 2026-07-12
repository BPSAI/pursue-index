"""The actionable tranche-ready surface appended to the poll alert.

The Release-4 gap was not detection (that fired in 90s) but that the alert only
carried verdict+counts — not the work-list, cost, or the command to run. This
builder produces the missing actionable block, credential-free.
"""

from __future__ import annotations

from pursue_index.release.ship import build_tranche_ready_summary


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


def test_summary_caps_worklist_and_notes_remainder():
    ids = [f"card{i:02d}" for i in range(40)]
    s = _summary(scoped_count=40, scoped_ids=ids)
    # First few are shown; an overflow-count note appears rather than 40 lines.
    assert "card00" in s
    assert "more" in s.lower()
