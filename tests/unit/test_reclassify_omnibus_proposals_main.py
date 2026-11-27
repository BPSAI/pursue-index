"""Characterization tests for scripts/reclassify_omnibus_proposals.py main()."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import reclassify_omnibus_proposals as ro  # noqa: E402


def _setup(tmp_path: Path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "cards": [
                    {"card_id": "A", "asset_filename": "FBI_62-HQ-83894_Section_3.pdf", "title": "Sec three"},
                    {"card_id": "B", "asset_filename": "memo.pdf", "title": "A memo"},
                    {"card_id": "C", "asset_filename": "DOW_Box_7.pdf", "title": "Box seven"},
                ]
            }
        )
    )
    proposals = tmp_path / "p.jsonl"
    rows = [
        {
            "card_id": "A",
            "display_date": "1950-01-02",
            "display_date_range": None,
            "display_date_evidence": "ev",
            "display_date_evidence_card_ref": "ref",
            "display_date_curator": "cur",
            "display_date_approved_at": "x",
            "_proposal_metadata": {"k": 1},
        },
        {"card_id": "B", "display_date": "1960-01-01"},
        {"card_id": "C", "display_date": None, "display_date_abstention": "mine"},
    ]
    proposals.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n\n")
    return manifest, proposals, rows


def _expected_rewrite(row):
    return {
        "card_id": "A",
        "display_date": None,
        "display_date_range": None,
        "display_date_evidence": "ev",
        "display_date_evidence_card_ref": "ref",
        "display_date_abstention": ro._match_pattern("FBI_62-HQ-83894_Section_3.pdf", "Sec three"),
        "display_date_curator": "cur",
        "display_date_approved_at": None,
        "_proposal_metadata": {
            "k": 1,
            "reclassified_as_omnibus": True,
            "agent_original_proposal": {
                "display_date": "1950-01-02",
                "display_date_range": None,
                "display_date_evidence": "ev",
                "display_date_evidence_card_ref": "ref",
            },
        },
    }


_SUMMARY = (
    "Proposals: 3 total\n"
    "  rewritten as omnibus abstentions: 1\n"
    "  already abstaining (left alone):  1\n"
    "  untouched (single-document):       1\n"
    "\n"
    "Rewritten cards:\n"
    "  A  was: 1950-01-02    Sec three\n"
)


def test_write_path(tmp_path, capsys):
    manifest, proposals, rows = _setup(tmp_path)
    rc = ro.main(["--proposals", str(proposals), "--manifest", str(manifest)])
    assert rc == 0
    assert capsys.readouterr().out == _SUMMARY + f"\nWrote 3 rows to {proposals}\n"
    got = [json.loads(line) for line in proposals.read_text().splitlines()]
    assert got == [_expected_rewrite(rows[0]), rows[1], rows[2]]
    assert not proposals.with_suffix(".jsonl.tmp").exists()


def test_dry_run_writes_nothing(tmp_path, capsys):
    manifest, proposals, _ = _setup(tmp_path)
    before = proposals.read_text()
    rc = ro.main(["--proposals", str(proposals), "--manifest", str(manifest), "--dry-run"])
    assert rc == 0
    assert capsys.readouterr().out == _SUMMARY + "\n(dry-run; no file written)\n"
    assert proposals.read_text() == before


def test_no_proposals_returns_1(tmp_path, capsys):
    manifest, _, _ = _setup(tmp_path)
    missing = tmp_path / "none.jsonl"
    rc = ro.main(["--proposals", str(missing), "--manifest", str(manifest)])
    assert rc == 1
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err == f"No proposals at {missing}\n"


def test_unknown_card_untouched_and_no_changes_section(tmp_path, capsys):
    manifest, _, _ = _setup(tmp_path)
    p = tmp_path / "q.jsonl"
    p.write_text(json.dumps({"card_id": "ZZ", "display_date": "1999-01-01"}) + "\n")
    rc = ro.main(["--proposals", str(p), "--manifest", str(manifest), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Rewritten cards:" not in out
    assert "untouched (single-document):       1" in out
