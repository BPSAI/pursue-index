"""``scripts/check_disposition_evidence.py``: each row's evidence_ref matches a report's sha256.

The reports are private, so the tests use fixture files in a temp directory.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_disposition_evidence as checker  # noqa: E402

REPORT = b"fixture evidence report, as posted\n"
REF = hashlib.sha256(REPORT).hexdigest()


def _row(card: str, ref: str) -> str:
    return json.dumps({
        "card_id": card, "old_sha256": "a" * 64, "new_sha256": "b" * 64,
        "disposition": "resave-content-verified", "reviewed_at": "2026-11-21",
        "evidence": "re-save", "evidence_ref": ref, "ocr_from": "a" * 64,
    }) + "\n"


@pytest.fixture
def setup(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "report-1.md").write_bytes(REPORT)
    (evidence / "other.txt").write_bytes(b"unrelated")
    rows = tmp_path / "dispositions.jsonl"
    return evidence, rows


def _run(rows, evidence, capsys):
    code = checker.main(["--dispositions", str(rows), "--evidence-dir", str(evidence)])
    out = capsys.readouterr()
    return code, out.out + out.err


def test_every_ref_matching_a_report_passes(setup, capsys):
    evidence, rows = setup
    rows.write_text(_row("7d1b50162c29378a", REF) + _row("3a5445e8aa7985d4", REF))
    code, out = _run(rows, evidence, capsys)
    assert code == 0 and "2 row(s)" in out and "OK" in out


def test_a_ref_matching_no_report_fails_and_names_the_card(setup, capsys):
    evidence, rows = setup
    rows.write_text(_row("7d1b50162c29378a", REF) + _row("3a5445e8aa7985d4", "c" * 64))
    code, out = _run(rows, evidence, capsys)
    assert code == 1
    assert "3a5445e8aa7985d4" in out and "7d1b50162c29378a" not in out


def test_a_report_with_a_different_byte_does_not_match(setup, capsys):
    evidence, rows = setup
    (evidence / "report-1.md").write_bytes(REPORT + b" ")  # edited after the ref was taken
    rows.write_text(_row("7d1b50162c29378a", REF))
    code, _ = _run(rows, evidence, capsys)
    assert code == 1


def test_missing_evidence_dir_fails_closed(setup, capsys, tmp_path):
    _, rows = setup
    rows.write_text(_row("7d1b50162c29378a", REF))
    code, out = _run(rows, tmp_path / "nope", capsys)
    assert code == 1 and "evidence" in out


def test_empty_evidence_dir_fails_when_rows_exist(setup, tmp_path, capsys):
    _, rows = setup
    empty = tmp_path / "empty"
    empty.mkdir()
    rows.write_text(_row("7d1b50162c29378a", REF))
    code, _ = _run(rows, empty, capsys)
    assert code == 1


def test_malformed_dispositions_file_fails(setup, capsys):
    evidence, rows = setup
    rows.write_text("{not json}\n")
    code, out = _run(rows, evidence, capsys)
    assert code == 1 and "ERROR" in out


def test_no_rows_is_ok(setup, capsys):
    evidence, rows = setup
    rows.write_text("")
    code, _ = _run(rows, evidence, capsys)
    assert code == 0


def test_subdirectories_are_searched(setup, capsys):
    evidence, rows = setup
    (evidence / "sub").mkdir()
    (evidence / "sub" / "r.md").write_bytes(b"nested report")
    rows.write_text(_row("7d1b50162c29378a", hashlib.sha256(b"nested report").hexdigest()))
    code, _ = _run(rows, evidence, capsys)
    assert code == 0
