"""Tests for `pursue_index.tranche.field_diff` / `pair_rows_by_identity`
on duplicate card_id groups.

A card_id can carry more than one manifest row -- a PDF row plus one or
more VID rows sharing the same card_id (9 such ids live in the real
375-card manifest). Keying a plain dict by card_id and collapsing to
"last row wins" before diffing compares mismatched rows (a VID row
against a PDF row) and either fabricates changes or silently drops a
real change on whichever row didn't survive the collapse. Split out of
`test_tranche_diff.py` to stay under the arch-check function-count limit
(see `.claude/rules/architecture.md`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for p in (_SRC, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import tranche_diff  # noqa: E402

from pursue_index.tranche import field_diff, pair_rows_by_identity  # noqa: E402


def _card(card_id: str, **kw) -> dict:
    """Build a manifest card dict with sensible defaults (mirrors the
    fixture in test_tranche_diff.py)."""
    base = {
        "card_id": card_id,
        "title": "",
        "asset_type": "PDF",
        "agency": None,
        "incident_date": None,
        "incident_location": None,
        "asset_filename": None,
        "asset_url": None,
        "video_title": None,
    }
    base.update(kw)
    return base


def _pdf_row(card_id: str, **kw) -> dict:
    return _card(card_id, asset_type="PDF", **kw)


def _vid_row(card_id: str, **kw) -> dict:
    return _card(card_id, asset_type="VID", **kw)


def _manifest(cards: list[dict]) -> dict:
    return {"csv_sha256": "fake", "cards": cards}


def test_pair_rows_by_identity_pairs_pdf_with_pdf_never_vid() -> None:
    old_rows = [
        _pdf_row("aa11", asset_url="https://x/a.pdf", title="PDF title"),
        _vid_row("aa11", asset_url="https://x/a.pdf", video_title="Video title"),
    ]
    new_rows = [
        _pdf_row("aa11", asset_url="https://x/a.pdf", title="PDF title (rev)"),
        _vid_row("aa11", asset_url="https://x/a.pdf", video_title="Video title"),
    ]
    pairs = pair_rows_by_identity(old_rows, new_rows)
    assert len(pairs) == 2
    for old, new in pairs:
        assert old["asset_type"] == new["asset_type"]


def test_pair_rows_by_identity_pairs_same_key_rows_positionally() -> None:
    # Three VID rows sharing one identity key (same asset_url/video_title)
    # -- must pair positionally, not fan out or drop.
    old_rows = [_vid_row("bb22", asset_url="https://x/b.pdf", video_title="V",
                          title=f"PR{i}") for i in range(3)]
    new_rows = [_vid_row("bb22", asset_url="https://x/b.pdf", video_title="V",
                          title=f"PR{i}") for i in range(3)]
    new_rows[1] = {**new_rows[1], "incident_location": "Türkiye"}
    pairs = pair_rows_by_identity(old_rows, new_rows)
    assert len(pairs) == 3
    diffs = [field_diff([o], [n]) for o, n in pairs]
    changed = [d for d in diffs if d]
    assert len(changed) == 1
    assert changed[0] == [{"field": "incident_location", "old": None, "new": "Türkiye"}]


def test_field_diff_self_diff_of_pdf_plus_vid_group_is_empty() -> None:
    # The live symptom this task fixes: a last-wins collapse compared the
    # VID row to the PDF row and reported title/asset_type/etc as
    # "changed" even when nothing actually changed.
    rows = [
        _pdf_row("cc33", asset_url="https://x/c.pdf", title="Mission Report"),
        _vid_row("cc33", asset_url="https://x/c.pdf", video_title="Video Title"),
    ]
    assert field_diff(rows, rows) == []


def test_field_diff_never_diffs_pdf_row_against_vid_row() -> None:
    old_rows = [
        _pdf_row("dd44", asset_url="https://x/d.pdf", title="Old PDF title"),
        _vid_row("dd44", asset_url="https://x/d.pdf", video_title="Video Title"),
    ]
    new_rows = [
        _pdf_row("dd44", asset_url="https://x/d.pdf", title="New PDF title"),
        _vid_row("dd44", asset_url="https://x/d.pdf", video_title="Video Title"),
    ]
    diffs = field_diff(old_rows, new_rows)
    assert diffs == [{"field": "title", "old": "Old PDF title", "new": "New PDF title"}]


def test_field_diff_reports_change_on_non_last_row_of_duplicate_id() -> None:
    """AC: a duplicate id whose non-last row changes must be reported.

    The PDF row is FIRST in manifest order, the VID row LAST. A naive
    `{c["card_id"]: c for c in cards}` comprehension survives with the
    VID row (last wins) on both sides, so a change on the PDF row (the
    non-last row) would be silently invisible to the old collapse-based
    diff. It must still be reported here.
    """
    old_rows = [
        _pdf_row("ee55", asset_url="https://x/e.pdf", incident_location="Iraq"),
        _vid_row("ee55", asset_url="https://x/e.pdf", video_title="Video Title"),
    ]
    new_rows = [
        _pdf_row("ee55", asset_url="https://x/e.pdf", incident_location="Syria"),
        _vid_row("ee55", asset_url="https://x/e.pdf", video_title="Video Title"),
    ]
    diffs = field_diff(old_rows, new_rows)
    assert diffs == [{"field": "incident_location", "old": "Iraq", "new": "Syria"}]


def test_diff_tranches_reports_change_on_non_last_row_of_duplicate_id() -> None:
    """Same regression, exercised end-to-end through diff_tranches so the
    receipt-generation path (not just the pure helper) is covered."""
    old_manifest = _manifest([
        _pdf_row("ee55", asset_url="https://x/e.pdf", incident_location="Iraq"),
        _vid_row("ee55", asset_url="https://x/e.pdf", video_title="Video Title"),
    ])
    new_manifest = _manifest([
        _pdf_row("ee55", asset_url="https://x/e.pdf", incident_location="Syria"),
        _vid_row("ee55", asset_url="https://x/e.pdf", video_title="Video Title"),
    ])
    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=lambda url: None,
    )
    assert len(result["field_only_changes"]) == 1
    fc = result["field_only_changes"][0]
    assert fc["card_id"] == "ee55"
    assert fc["diffs"] == [{"field": "incident_location", "old": "Iraq", "new": "Syria"}]
