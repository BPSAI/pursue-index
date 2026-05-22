"""Tests for ``pursue_index.clean.qc.runner``.

Per-card runner that iterates cleaned-but-not-judged pages and writes
verdicts to the QC sidecar. Tests use a fake judge callable so we
don't hit Anthropic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.clean.qc import judge, runner


def _make_cleaned_row(page: int, text: str, *, raw_sha: str | None = None) -> dict:
    row = {
        "id": f"abcd-p{page}",
        "card_id": "abcd",
        "page": page,
        "text_cleaned": text,
        "model_id": "claude-haiku-4-5",
        "prompt_sha256": "cleaner_prompt_sha",
        "input_sha256": raw_sha or f"raw_{page}",
        "output_sha256": f"cleaned_{page}",
        "idempotency_key": f"key_{page}",
        "generated_at": "2026-05-12T14:00:00Z",
    }
    return row


def _make_raw_row(page: int, text: str) -> dict:
    return {"page": page, "text": text, "confidence": 0.95}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# A fake grade_page that returns a pre-set result. Mirrors judge.grade_page's
# signature so we can monkeypatch it into the runner.
def _make_fake_judge(verdict_seq: list[str], *, model_id: str = "claude-sonnet-4-6"):
    """Build a fake grade_page returning all-pass or all-soft-fail results."""
    calls = []
    def fake_grade_page(*, raw_text: str, cleaned_text: str, model_id: str):
        verdict = verdict_seq[len(calls) % len(verdict_seq)]
        calls.append({"raw": raw_text[:30], "cleaned": cleaned_text[:30]})
        check_body = (
            {"verdict": verdict, "evidence": "", "severity": "none"}
            if verdict != "hard_fail"
            else {"verdict": "hard_fail", "evidence": "test", "severity": "high"}
        )
        ratio_body = {"verdict": verdict, "ratio": 1.0, "severity": "none"}
        checks = {
            "hallucinated_facts":     check_body,
            "fabricated_redactions":  check_body,
            "length_ratio":           ratio_body,
            "voice_match":            check_body,
            "page_boundary_fidelity": check_body,
            "ocr_artifact_handling":  check_body,
            "verbatim_quotability":   check_body,
            "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
        }
        return judge.GradeResult(
            checks=checks,
            usage={"input_tokens": 1500, "output_tokens": 400,
                   "cache_read_tokens": 0, "cache_creation_tokens": 0},
            judge_skipped=None,
        )
    return fake_grade_page, calls


def test_run_card_grades_each_cleaned_page(tmp_path: Path) -> None:
    raw_path = tmp_path / "abcd" / "pages.jsonl"
    cleaned_path = tmp_path / "abcd" / "pages_cleaned.jsonl"
    qc_path = tmp_path / "abcd" / "pages_cleaned_qc.jsonl"
    _write_jsonl(raw_path, [
        _make_raw_row(1, "first page raw"),
        _make_raw_row(2, "second page raw"),
    ])
    _write_jsonl(cleaned_path, [
        _make_cleaned_row(1, "first page cleaned", raw_sha=f"raw_1"),
        _make_cleaned_row(2, "second page cleaned", raw_sha=f"raw_2"),
    ])
    fake_grade, calls = _make_fake_judge(["pass"])

    report = runner.run_card(
        card_id="abcd",
        raw_path=raw_path,
        cleaned_path=cleaned_path,
        qc_path=qc_path,
        judge_model_id="claude-sonnet-4-6",
        budget_usd=10.0,
        grade_fn=fake_grade,
    )

    assert report.pages_graded == 2
    assert report.pages_skipped == 0
    assert len(calls) == 2
    # Verify the sidecar got 2 rows
    rows = [json.loads(ln) for ln in qc_path.read_text().splitlines() if ln.strip()]
    assert len(rows) == 2
    assert all(r["aggregate"]["verdict"] == "pass" for r in rows)


def test_run_card_skips_already_graded_pages(tmp_path: Path) -> None:
    """Existing QC rows with matching 4-tuple should not re-grade."""
    raw_path = tmp_path / "abcd" / "pages.jsonl"
    cleaned_path = tmp_path / "abcd" / "pages_cleaned.jsonl"
    qc_path = tmp_path / "abcd" / "pages_cleaned_qc.jsonl"
    _write_jsonl(raw_path, [_make_raw_row(1, "first page raw")])
    cleaned_row = _make_cleaned_row(1, "first page cleaned", raw_sha="raw_1")
    _write_jsonl(cleaned_path, [cleaned_row])
    # Pre-seed a QC row matching the 4-tuple
    qc_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.write_text(json.dumps({
        "page": 1,
        "raw_sha256": "raw_1",
        "cleaned_sha256": cleaned_row["output_sha256"],
        "judge_model_id": "claude-sonnet-4-6",
        "judge_prompt_sha256": "test_prompt_sha",
    }) + "\n")
    fake_grade, calls = _make_fake_judge(["pass"])

    report = runner.run_card(
        card_id="abcd",
        raw_path=raw_path,
        cleaned_path=cleaned_path,
        qc_path=qc_path,
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha="test_prompt_sha",
        budget_usd=10.0,
        grade_fn=fake_grade,
    )
    assert report.pages_graded == 0
    assert report.pages_skipped == 1
    assert len(calls) == 0


def test_run_card_respects_budget_cap(tmp_path: Path) -> None:
    """When estimated spend exceeds the cap, the runner raises mid-card."""
    raw_path = tmp_path / "abcd" / "pages.jsonl"
    cleaned_path = tmp_path / "abcd" / "pages_cleaned.jsonl"
    qc_path = tmp_path / "abcd" / "pages_cleaned_qc.jsonl"
    rows = []
    for i in range(1, 11):
        rows.append(_make_raw_row(i, f"raw page {i}"))
    _write_jsonl(raw_path, rows)
    crows = [_make_cleaned_row(i, f"cleaned page {i}", raw_sha=f"raw_{i}") for i in range(1, 11)]
    _write_jsonl(cleaned_path, crows)
    # Inflate the fake usage so 1 call ≈ $5
    def expensive_grade(*, raw_text: str, cleaned_text: str, model_id: str):
        return judge.GradeResult(
            checks={
                "hallucinated_facts":     {"verdict": "pass", "evidence": "", "severity": "none"},
                "fabricated_redactions":  {"verdict": "pass", "evidence": "", "severity": "none"},
                "length_ratio":           {"verdict": "pass", "ratio": 1.0, "severity": "none"},
                "voice_match":            {"verdict": "pass", "evidence": "", "severity": "none"},
                "page_boundary_fidelity": {"verdict": "pass", "evidence": "", "severity": "none"},
                "ocr_artifact_handling":  {"verdict": "pass", "evidence": "", "severity": "none"},
                "verbatim_quotability":   {"verdict": "pass", "evidence": "", "severity": "none"},
                "interpretive_cleanups":  {"count": 0, "examples": [], "severity": "none"},
            },
            usage={"input_tokens": 1_000_000, "output_tokens": 200_000,
                   "cache_read_tokens": 0, "cache_creation_tokens": 0},
            judge_skipped=None,
        )
    with pytest.raises(runner.QcBudgetExceededError):
        runner.run_card(
            card_id="abcd",
            raw_path=raw_path,
            cleaned_path=cleaned_path,
            qc_path=qc_path,
            judge_model_id="claude-sonnet-4-6",
            budget_usd=5.0,
            grade_fn=expensive_grade,
        )


def test_run_card_handles_judge_skip(tmp_path: Path) -> None:
    """Judge content-filter rejections should write a skip row, not crash."""
    raw_path = tmp_path / "abcd" / "pages.jsonl"
    cleaned_path = tmp_path / "abcd" / "pages_cleaned.jsonl"
    qc_path = tmp_path / "abcd" / "pages_cleaned_qc.jsonl"
    _write_jsonl(raw_path, [_make_raw_row(1, "first page raw")])
    _write_jsonl(cleaned_path, [_make_cleaned_row(1, "cleaned", raw_sha="raw_1")])
    def fake_skip(*, raw_text: str, cleaned_text: str, model_id: str):
        return judge.GradeResult(
            checks=None,
            usage={"input_tokens": 0, "output_tokens": 0,
                   "cache_read_tokens": 0, "cache_creation_tokens": 0},
            judge_skipped="content_filter",
        )
    report = runner.run_card(
        card_id="abcd",
        raw_path=raw_path,
        cleaned_path=cleaned_path,
        qc_path=qc_path,
        judge_model_id="claude-sonnet-4-6",
        budget_usd=10.0,
        grade_fn=fake_skip,
    )
    assert report.pages_graded == 0
    assert report.pages_skipped_judge == 1
    rows = [json.loads(ln) for ln in qc_path.read_text().splitlines() if ln.strip()]
    assert rows[0]["judge_skipped"] == "content_filter"
    assert rows[0]["aggregate"]["verdict"] == "not_applicable"
