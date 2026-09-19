"""Shared shrink guard for the derivative builders.

``build_search_data.py`` / ``build_embed_data.py`` regenerate committed
payloads wholesale from the data root. On a root that holds OCR for only the
new cards that silently drops every other card, so both builders compare their
result against the committed payload and refuse to shrink it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.release.shrink_guard import (
    committed_embed_card_ids,
    committed_pages_card_ids,
    enforce,
    find_shrink,
    find_uncovered,
    ocr_covered_ids,
    ocr_dir_error,
)


def _card(card_id: str, asset_type: str = "PDF") -> dict[str, str]:
    return {"card_id": card_id, "asset_type": asset_type}


def _stage_ocr(ocr_dir: Path, card_id: str, status: str = "ok") -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": status}))
    (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "t"}) + "\n")


def test_committed_ids_absent_file_is_none(tmp_path: Path) -> None:
    assert committed_pages_card_ids(tmp_path / "pages.json") is None
    assert committed_embed_card_ids(tmp_path / "embed_index.json") is None


def test_committed_ids_read_both_payload_shapes(tmp_path: Path) -> None:
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps([{"card_id": "a", "page": 1}, {"card_id": "b", "page": 1}]))
    embed = tmp_path / "embed_index.json"
    embed.write_text(json.dumps({"n": 2, "pages": [["a", 1], ["c", 2]]}))
    assert committed_pages_card_ids(pages) == {"a", "b"}
    assert committed_embed_card_ids(embed) == {"a", "c"}


def test_missing_baseline_warns_and_does_not_crash(
    tmp_path: Path, capsys
) -> None:
    assert committed_pages_card_ids(tmp_path / "pages.json") is None
    assert committed_embed_card_ids(tmp_path / "embed_index.json") is None
    err = capsys.readouterr().err
    assert "no committed pages.json" in err and "no committed embed_index.json" in err


def test_ocr_dir_error_flags_unreadable_root(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "ocr"
    not_a_dir.write_text("x")
    assert ocr_dir_error(not_a_dir) is not None
    assert ocr_dir_error(tmp_path) is None


def test_ocr_dir_error_tolerates_absent_root(tmp_path: Path) -> None:
    """An absent ocr dir is an empty root; the shrink/coverage rules catch it."""
    assert ocr_dir_error(tmp_path / "missing") is None


def test_find_shrink_lists_dropped_ids_sorted() -> None:
    assert find_shrink({"c", "a", "b"}, {"a"}) == ["b", "c"]


def test_find_shrink_growth_and_no_baseline_are_clean() -> None:
    assert find_shrink({"a"}, {"a", "b"}) == []
    assert find_shrink(None, {"a"}) == []


def test_find_uncovered_flags_pdf_card_without_text() -> None:
    cards = [_card("a"), _card("b")]
    assert find_uncovered(cards, {"a"}) == ["b"]


def test_find_uncovered_ignores_types_with_no_text_by_nature() -> None:
    """VID has no transcript pipeline and a pending AUD/IMG card is a backlog,
    not a shrink; flagging them would fail the real committed tree."""
    cards = [_card("v", "VID"), _card("i", "IMG"), _card("u", "AUD")]
    assert find_uncovered(cards, set()) == []


def test_ocr_covered_ids_needs_ok_meta_and_pages(tmp_path: Path) -> None:
    ocr = tmp_path / "ocr"
    _stage_ocr(ocr, "good")
    _stage_ocr(ocr, "failed", status="failed")
    (ocr / "nopages").mkdir()
    (ocr / "nopages" / "meta.json").write_text(json.dumps({"status": "ok"}))
    (ocr / "stray.txt").write_text("x")
    assert ocr_covered_ids(ocr) == {"good"}
    assert ocr_covered_ids(tmp_path / "missing") == set()


def test_ocr_covered_ids_counts_transcript_sidecar(tmp_path: Path) -> None:
    """A transcript lands in the same ``ocr/<card_id>/`` path (engine
    ``assemblyai``), so a transcript-only card counts as covered."""
    ocr = tmp_path / "ocr"
    _stage_ocr(ocr, "aud1")
    (ocr / "aud1" / "meta.json").write_text(
        json.dumps({"status": "ok", "engine": "assemblyai"})
    )
    assert ocr_covered_ids(ocr) == {"aud1"}


def test_enforce_clean_returns_zero_and_writes_nothing(tmp_path: Path) -> None:
    log = tmp_path / "audit-log.jsonl"
    assert enforce("x.py", [], [], allow_reason=None, audit_log=log) == 0
    assert not log.exists()


def test_enforce_refuses_and_names_ids(tmp_path: Path, capsys) -> None:
    log = tmp_path / "audit-log.jsonl"
    rc = enforce("x.py", ["m1", "m2"], ["u1"], allow_reason=None, audit_log=log)
    err = capsys.readouterr().err
    assert rc == 1
    assert "m1" in err and "m2" in err and "u1" in err
    assert not log.exists()


def test_enforce_allowed_appends_audit_row(tmp_path: Path) -> None:
    log = tmp_path / "data" / "audit-log.jsonl"
    rc = enforce("x.py", ["m1"], ["u1"], allow_reason="card removed", audit_log=log)
    assert rc == 0
    (row,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert row["event"] == "allow_shrink"
    assert row["script"] == "x.py"
    assert row["reason"] == "card removed"
    assert row["shrunk"] == ["m1"]
    assert row["uncovered"] == ["u1"]
    assert row["at"]


def test_enforce_appends_after_existing_rows(tmp_path: Path) -> None:
    log = tmp_path / "audit-log.jsonl"
    log.write_text('{"tranche_sha256": "abc"}\n')
    enforce("x.py", ["m1"], [], allow_reason="r", audit_log=log)
    assert len(log.read_text().splitlines()) == 2


def test_enforce_blank_reason_is_not_an_exception(tmp_path: Path) -> None:
    log = tmp_path / "audit-log.jsonl"
    assert enforce("x.py", ["m1"], [], allow_reason="  ", audit_log=log) == 1
    assert not log.exists()
