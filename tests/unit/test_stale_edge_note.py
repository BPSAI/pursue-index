"""Stale-edge observations leave a small note, never the CSV bytes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import stale_edge_note as n  # noqa: E402

SHA = "a" * 64
LM = "Fri, 18 Sep 2026 15:05:12 GMT"


def test_note_records_sha_size_header_and_time(tmp_path: Path) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / f"{SHA}.csv").write_bytes(b"12345")
    path = n.write_note(tmp_path / "notes", SHA, LM, csv_dir, now="2026-10-27T10:00:00Z")
    note = json.loads(path.read_text())
    assert note == {"sha256": SHA, "size": 5, "last_modified": LM, "fetched_at": "2026-10-27T10:00:00Z"}
    assert path.stat().st_size <= n.MAX_NOTE_BYTES


def test_hostile_header_is_filtered_and_bounded(tmp_path: Path) -> None:
    path = n.write_note(tmp_path / "notes", SHA, "<script>`@x`\n" + "A" * 5000, tmp_path, now="t")
    text = path.read_text()
    assert path.stat().st_size <= n.MAX_NOTE_BYTES
    assert "<" not in text and "`" not in text and "@" not in text


def test_one_note_per_sha_is_idempotent(tmp_path: Path) -> None:
    first = n.write_note(tmp_path / "notes", SHA, LM, tmp_path, now="2026-10-27T10:00:00Z")
    before = first.read_bytes()
    again = n.write_note(tmp_path / "notes", SHA, LM, tmp_path, now="2026-10-28T10:00:00Z")
    assert again == first and first.read_bytes() == before


def test_directory_is_capped_oldest_pruned(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    for i in range(n.MAX_NOTES + 5):
        n.write_note(notes, f"{i:064x}", LM, tmp_path, now=f"2026-10-27T10:{i // 60:02d}:{i % 60:02d}Z")
    names = sorted(p.name for p in notes.glob("*.json"))
    assert len(names) == n.MAX_NOTES
    assert f"{0:064x}.json" not in names and f"{n.MAX_NOTES + 4:064x}.json" in names


@pytest.mark.parametrize("bad", ["../x", "abc", ""])
def test_malformed_sha_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        n.write_note(tmp_path / "notes", bad, LM, tmp_path, now="t")


def test_main_writes_the_note(tmp_path: Path) -> None:
    rc = n.main([SHA, "--last-modified", LM, "--notes-dir", str(tmp_path / "notes"),
                 "--csv-dir", str(tmp_path)])
    assert rc == 0 and (tmp_path / "notes" / f"{SHA}.json").is_file()
