"""Tests for the per-card ``pages_cleaned.jsonl`` sidecar I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.clean import sidecar


def test_load_existing_returns_empty_when_no_file(tmp_path: Path) -> None:
    """Sidecar that doesn't exist yet → empty dict (first run, all work TBD)."""
    rows = sidecar.load_existing(tmp_path / "pages_cleaned.jsonl")
    assert rows == {}


def test_load_existing_keys_rows_by_page(tmp_path: Path) -> None:
    """Existing sidecar → {page_number: row dict}, parsed from JSONL."""
    path = tmp_path / "pages_cleaned.jsonl"
    path.write_text(
        json.dumps({"page": 1, "card_id": "c1", "text_cleaned": "p1"}) + "\n"
        + json.dumps({"page": 2, "card_id": "c1", "text_cleaned": "p2"}) + "\n"
    )
    rows = sidecar.load_existing(path)
    assert set(rows.keys()) == {1, 2}
    assert rows[1]["text_cleaned"] == "p1"


def test_load_existing_tolerates_blank_lines(tmp_path: Path) -> None:
    """Blank lines in the middle of a JSONL must not crash the loader.

    We've been bitten by editor-saved JSONLs with a trailing newline; the
    sidecar reader has to be lenient because the producer is `text + "\\n"`
    and partial writes can leave odd states.
    """
    path = tmp_path / "pages_cleaned.jsonl"
    path.write_text(
        json.dumps({"page": 3, "card_id": "c1"}) + "\n\n  \n"
        + json.dumps({"page": 4, "card_id": "c1"}) + "\n"
    )
    rows = sidecar.load_existing(path)
    assert set(rows.keys()) == {3, 4}


def test_write_row_appends_jsonl(tmp_path: Path) -> None:
    """Each call appends one JSON line, terminated with \\n."""
    path = tmp_path / "pages_cleaned.jsonl"
    sidecar.write_row(path, {"page": 1, "card_id": "c1", "text_cleaned": "x"})
    sidecar.write_row(path, {"page": 2, "card_id": "c1", "text_cleaned": "y"})
    body = path.read_text()
    assert body.endswith("\n")
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["page"] == 1
    assert json.loads(lines[1])["page"] == 2


def test_write_row_creates_parent_dir(tmp_path: Path) -> None:
    """If the per-card NAS dir doesn't exist yet, write_row creates it."""
    path = tmp_path / "ocr" / "deadbeef" / "pages_cleaned.jsonl"
    sidecar.write_row(path, {"page": 1, "card_id": "deadbeef"})
    assert path.exists()


def test_should_skip_when_input_sha_matches(tmp_path: Path) -> None:
    """Idempotency: same input_sha256 in existing row → skip cleaning.

    The runner reads the manifest of input rows, hashes each text, and asks
    ``should_skip(existing_row, new_input_sha)``. Match → skip. Mismatch
    (e.g. re-run after the OCR text changed) → re-clean.
    """
    row = {"page": 1, "input_sha256": "abc", "text_cleaned": "old"}
    assert sidecar.should_skip(row, new_input_sha="abc") is True
    assert sidecar.should_skip(row, new_input_sha="def") is False


def test_should_skip_when_row_is_missing_input_sha() -> None:
    """A row without input_sha256 (legacy / partial write) → never skip."""
    assert sidecar.should_skip({"page": 1}, new_input_sha="abc") is False
