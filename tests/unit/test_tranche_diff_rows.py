"""Row-level behaviour of the tranche receipt generator.

Two properties are pinned here:

  * A card_id that gains or loses a manifest row between two manifests
    is reported. Only the paired rows carry a field-level diff, so
    without a row-level section the change would not appear at all.
  * A card_id backed by several rows is DESCRIBED by its PDF row.
    Building `{card["card_id"]: card}` keeps whichever row happens to
    come last, so a removed or added card was described by the title and
    URL of one of its video rows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tranche_diff  # noqa: E402

from pursue_index.tranche_report import render_markdown  # noqa: E402

_PDF_URL = "https://x/d32.pdf"


def _row(card_id: str, **kw: Any) -> dict[str, Any]:
    base = {
        "card_id": card_id,
        "title": "",
        "asset_type": "PDF",
        "agency": "DOW",
        "incident_date": None,
        "incident_location": None,
        "asset_filename": None,
        "asset_url": None,
        "dvids_video_id": None,
        "video_title": None,
    }
    base.update(kw)
    return base


def _pdf(card_id: str, **kw: Any) -> dict[str, Any]:
    fields = {
        "asset_type": "PDF", "title": "Mission Report",
        "asset_url": _PDF_URL, "asset_filename": "d32.pdf",
    }
    fields.update(kw)
    return _row(card_id, **fields)


def _vid(card_id: str, dvids: str, **kw: Any) -> dict[str, Any]:
    fields = {
        "asset_type": "VID", "title": f"PR{dvids}", "asset_url": _PDF_URL,
        "asset_filename": "pr.mp4", "dvids_video_id": dvids,
        "video_title": "Unresolved UAP Report",
    }
    fields.update(kw)
    return _row(card_id, **fields)


def _manifest(cards: list[dict[str, Any]], sha: str = "fake") -> dict[str, Any]:
    return {"csv_sha256": sha, "cards": cards}


def _diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    return tranche_diff.diff_tranches(
        old_manifest=_manifest(old), new_manifest=_manifest(new),
        registry={}, fetch_byte_sha=lambda url: None,
    )


def test_added_row_under_an_existing_card_id_is_reported() -> None:
    old = [_pdf("aa11"), _vid("aa11", "1000001")]
    new = [*old, _vid("aa11", "1000002")]
    result = _diff(old, new)
    assert result["summary"]["row_changes"] == 1
    assert result["row_changes"] == [{
        "card_id": "aa11",
        "rows": [{"side": "added", "asset_type": "VID", "title": "PR1000002",
                  "asset_url": _PDF_URL, "dvids_video_id": "1000002"}],
    }]


def test_withdrawn_row_under_an_existing_card_id_is_reported() -> None:
    new = [_pdf("bb22"), _vid("bb22", "1000010")]
    old = [*new, _vid("bb22", "1000011")]
    result = _diff(old, new)
    assert result["summary"]["row_changes"] == 1
    rows = result["row_changes"][0]["rows"]
    assert [r["side"] for r in rows] == ["removed"]
    assert rows[0]["dvids_video_id"] == "1000011"


def test_unchanged_row_set_reports_no_row_changes() -> None:
    cards = [_pdf("cc33"), _vid("cc33", "1000020"), _vid("cc33", "1000021")]
    result = _diff(cards, list(reversed(cards)))
    assert result["row_changes"] == []
    assert result["summary"]["row_changes"] == 0


def test_row_changes_render_into_the_markdown_receipt() -> None:
    old = [_pdf("dd44"), _vid("dd44", "1000030")]
    new = [*old, _vid("dd44", "1000031")]
    md = render_markdown(_diff(old, new))
    assert "Row-level changes" in md
    assert "dd44" in md
    assert "1000031" in md


def _line_with(md: str, needle: str) -> str:
    return next(line for line in md.splitlines() if needle in line)


def test_a_pipe_in_a_title_does_not_break_the_row_changes_table() -> None:
    # Upstream titles are free text and do contain pipes. An unescaped one
    # opens a new table cell, shifting every column after it.
    old = [_pdf("hh88"), _vid("hh88", "1000070")]
    new = [*old, _vid("hh88", "1000071", title="PR1000071 | Greece | 2023")]
    md = render_markdown(_diff(old, new))
    line = _line_with(md, "1000071")
    assert line.count("|") - line.count("\\|") == 6, line
    assert "\\|" in line


def test_a_pipe_in_a_field_value_is_escaped_in_the_receipt() -> None:
    old = [_pdf("ii99")]
    new = [_pdf("ii99", title="Mission | Report")]
    md = render_markdown(_diff(old, new))
    assert "Mission \\| Report" in md


def test_a_newline_in_a_title_does_not_break_the_row_changes_table() -> None:
    # 1,813 upstream descriptions carry newlines — unlike pipes, which have
    # never actually appeared. A raw newline ends the table row mid-cell, so
    # the remaining columns render as body text under the table.
    old = [_pdf("jj10"), _vid("jj10", "1000080")]
    new = [*old, _vid("jj10", "1000081", title="PR1000081\nGreece\r\n2023")]
    md = render_markdown(_diff(old, new))
    line = _line_with(md, "1000081")
    assert "PR1000081 Greece 2023" in line
    assert line.count("|") == 6, line


def test_a_newline_in_a_field_value_is_collapsed_in_the_receipt() -> None:
    old = [_pdf("kk11")]
    new = [_pdf("kk11", title="Mission\nReport")]
    md = render_markdown(_diff(old, new))
    assert "Mission Report" in md
    assert "Mission\nReport" not in md


def test_a_newline_in_a_quarantined_title_stays_on_one_list_item() -> None:
    # The quarantined and restored sections interpolate upstream text into
    # markdown headings and list items, where a newline silently ends the
    # item and reflows the rest as a paragraph.
    diff = _diff([], [])
    diff["quarantined"] = [
        {
            "new_card_id": "ll12",
            "new_title": "Mission\nReport",
            "new_byte_sha256": "f" * 64,
            "new_asset_filename": "a\nb.pdf",
            "matches": [],
        }
    ]
    md = render_markdown(diff)
    assert "Mission Report" in md
    assert "Mission\nReport" not in md
    assert "a b.pdf" in md


def test_removed_duplicate_id_is_described_by_its_pdf_row() -> None:
    # The VID row comes last, so a last-wins dict describes this removal
    # with the video's title and filename instead of the document's.
    old = [_pdf("ee55"), _vid("ee55", "1000040")]
    result = _diff(old, [])
    assert result["removed"] == [{
        "card_id": "ee55", "title": "Mission Report",
        "asset_url": _PDF_URL, "asset_filename": "d32.pdf",
    }]


def test_added_duplicate_id_is_described_by_its_pdf_row() -> None:
    new = [_vid("ff66", "1000050"), _pdf("ff66")]
    result = _diff([], new)
    assert result["new_content"] == [{
        "new_card_id": "ff66", "title": "Mission Report",
        "asset_filename": "d32.pdf", "asset_url": _PDF_URL, "byte_sha256": None,
    }]


def test_added_duplicate_id_hashes_the_pdf_rows_url() -> None:
    fetched: list[str] = []

    def fetch(url: str) -> str | None:
        fetched.append(url)
        return None

    tranche_diff.diff_tranches(
        old_manifest=_manifest([]),
        new_manifest=_manifest([
            _vid("gg77", "1000060", asset_url="https://x/pr.mp4"),
            _pdf("gg77"),
        ]),
        registry={}, fetch_byte_sha=fetch,
    )
    assert fetched == [_PDF_URL]
