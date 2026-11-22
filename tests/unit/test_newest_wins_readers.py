"""Append-only OCR sidecars: every first-row reader keeps the newest row.

A re-run appends a second row for a page. The older row comes first in the
file and carries the earlier ``generated_at``; a reader must surface the newer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_llms_txt  # noqa: E402
import build_photo_card_index  # noqa: E402
import build_review_priority  # noqa: E402
import spotcheck_view  # noqa: E402

from pursue_index.page_rows import read_latest_pages  # noqa: E402

OLD = "2026-01-01T00:00:00+00:00"
NEW = "2026-06-01T00:00:00+00:00"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_read_latest_pages_keeps_newest_and_tolerates_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    lines = [
        json.dumps({"page": 1, "text": "old", "generated_at": OLD}),
        "",
        "{not json",
        json.dumps({"page": 1, "text": "new", "generated_at": NEW}),
        json.dumps({"page": 2, "text": "two", "generated_at": OLD}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = {r["page"]: r["text"] for r in read_latest_pages(path)}
    assert rows == {1: "new", 2: "two"}
    assert len(read_latest_pages(path)) == 2


def test_read_latest_pages_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_latest_pages(tmp_path / "absent.jsonl") == []


def test_spotcheck_find_row_returns_newest(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    _write(path, [
        {"page": 1, "text": "old", "generated_at": OLD},
        {"page": 1, "text": "new", "generated_at": NEW},
    ])
    row = spotcheck_view.find_row(path, 1)
    assert row is not None and row["text"] == "new"


def test_review_priority_one_entry_per_page_from_newest(tmp_path: Path) -> None:
    card = tmp_path / "c1"
    _write(card / "pages.jsonl", [
        {"page": 1, "text": "raw old", "confidence": 0.1, "generated_at": OLD},
        {"page": 1, "text": "raw new", "confidence": 0.9, "generated_at": NEW},
    ])
    _write(card / "pages_cleaned.jsonl", [
        {"page": 1, "text_cleaned": "old", "output_sha256": "old", "generated_at": OLD},
        {"page": 1, "text_cleaned": "new", "output_sha256": "new", "generated_at": NEW},
    ])
    out = build_review_priority.score_card("c1", card)
    assert len(out) == 1
    assert out[0]["cleaned_sha256"] == "new"
    assert out[0]["ocr_confidence"] == 0.9


def test_llms_excerpt_uses_newest_page_one(tmp_path: Path) -> None:
    _write(tmp_path / "c1" / "pages.jsonl", [
        {"page": 1, "text": "old text", "generated_at": OLD},
        {"page": 1, "text": "new text", "generated_at": NEW},
    ])
    assert build_llms_txt.first_page_excerpt("c1", ocr_dir=tmp_path) == "new text"


def test_photo_card_index_reads_newest_row(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    _write(path, [
        {"page": 1, "text": "long old text " * 50, "generated_at": OLD},
        {"page": 1, "text": "", "generated_at": NEW},
    ])
    assert build_photo_card_index._read_first_page_text(path) == ""


# --- spotcheck_view: a bad page never produces a traceback ------------------


def test_spotcheck_find_row_ignores_rows_with_missing_or_bad_page(tmp_path: Path) -> None:
    path = tmp_path / "pages_cleaned.jsonl"
    _write(path, [{"text_cleaned": "no page"}, {"page": "x", "text_cleaned": "bad"},
                  {"page": True, "text_cleaned": "bool"},
                  {"page": 1, "text_cleaned": "good", "generated_at": "2026-11-22T00:00:00Z"}])
    row = spotcheck_view.find_row(path, 1)
    assert row is not None and row["text_cleaned"] == "good"


def test_spotcheck_main_rejects_a_non_integer_page_argument(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["spotcheck_view.py", "0123456789abcdef", "two"])
    assert spotcheck_view.main() == 2
    err = capsys.readouterr().err
    assert "page must be a positive integer" in err and "Traceback" not in err


def test_spotcheck_main_rejects_a_non_positive_page_argument(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["spotcheck_view.py", "0123456789abcdef", "0"])
    assert spotcheck_view.main() == 2
    assert "page must be a positive integer" in capsys.readouterr().err


def test_a_boolean_page_is_corrupt_not_page_one(tmp_path: Path) -> None:
    from pursue_index.page_rows import latest_per_page
    rows = [{"page": 1, "text": "real", "generated_at": "2026-11-21T00:00:00Z"},
            {"page": True, "text": "bool", "generated_at": "2026-11-22T00:00:00Z"}]
    kept = latest_per_page(rows, "c")
    assert [r["text"] for r in kept] == ["real"]
