"""Tests for ``scripts/build_qc_summary.py``.

Aggregates per-card ``pages_cleaned_qc.jsonl`` files into a
corpus-wide snapshot used by the methodology page.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import build_qc_summary as bqs  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _qc_row(page: int, verdict: str, hard: int = 0, soft: int = 0) -> dict:
    return {
        "page": page,
        "raw_sha256": f"raw_{page}",
        "cleaned_sha256": f"cleaned_{page}",
        "judge_model_id": "claude-sonnet-4-6",
        "judge_prompt_sha256": "prompt_x",
        "checks": {},
        "aggregate": {
            "verdict": verdict,
            "hard_fail_count": hard,
            "soft_fail_count": soft,
        },
    }


def test_aggregate_empty_returns_zero_counts(tmp_path: Path) -> None:
    snapshot = bqs.aggregate(ocr_dir=tmp_path, card_ids=[])
    assert snapshot["total_pages_graded"] == 0
    assert snapshot["graded_pass_count"] == 0
    assert snapshot["graded_hard_fail_count"] == 0


def test_aggregate_counts_pass_soft_hard(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "aaaa" / "pages_cleaned_qc.jsonl", [
        _qc_row(1, "pass"),
        _qc_row(2, "pass"),
        _qc_row(3, "soft_fail", soft=2),
        _qc_row(4, "hard_fail", hard=1),
    ])
    snapshot = bqs.aggregate(ocr_dir=tmp_path, card_ids=["aaaa"])
    assert snapshot["total_pages_graded"] == 4
    assert snapshot["graded_pass_count"] == 2
    assert snapshot["graded_soft_fail_count"] == 1
    assert snapshot["graded_hard_fail_count"] == 1


def test_aggregate_includes_judge_skipped(tmp_path: Path) -> None:
    row = _qc_row(1, "not_applicable")
    row["judge_skipped"] = "content_filter"
    _write_jsonl(tmp_path / "aaaa" / "pages_cleaned_qc.jsonl", [row])
    snapshot = bqs.aggregate(ocr_dir=tmp_path, card_ids=["aaaa"])
    assert snapshot["judge_skipped_count"] == 1
    assert snapshot["judge_skipped_by_reason"]["content_filter"] == 1


def test_aggregate_handles_missing_card_dir(tmp_path: Path) -> None:
    snapshot = bqs.aggregate(ocr_dir=tmp_path, card_ids=["nonexistent"])
    assert snapshot["total_pages_graded"] == 0


def test_build_writes_snapshot_json(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "aaaa" / "pages_cleaned_qc.jsonl", [_qc_row(1, "pass")])
    out_path = tmp_path / "snap.json"
    bqs.build(ocr_dir=tmp_path, card_ids=["aaaa"], out_path=out_path)
    payload = json.loads(out_path.read_text())
    assert payload["total_pages_graded"] == 1
    assert payload["generated_at"]
    assert "judge_model" in payload
