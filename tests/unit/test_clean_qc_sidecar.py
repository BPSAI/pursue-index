"""Tests for ``pursue_index.clean.qc.sidecar``.

JSONL I/O contract: append-only ``pages_cleaned_qc.jsonl`` next to the
existing ``pages_cleaned.jsonl``. Idempotency on
``(raw_sha256, cleaned_sha256, judge_model_id, judge_prompt_sha256)``.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.clean.qc import sidecar


# --- load_existing -------------------------------------------------------


def test_load_existing_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert sidecar.load_existing(tmp_path / "absent.jsonl") == {}


def test_load_existing_skips_blank_and_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "qc.jsonl"
    p.write_text(
        '\n'
        '{"page": 1, "raw_sha256": "aa"}\n'
        '\n'
        'not json\n'
        '   \n'
        '{"page": 2, "raw_sha256": "bb"}\n'
    )
    rows = sidecar.load_existing(p)
    assert set(rows.keys()) == {1, 2}
    assert rows[1]["raw_sha256"] == "aa"


# --- write_row roundtrip -------------------------------------------------


def test_write_row_appends_to_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "qc.jsonl"
    sidecar.write_row(p, {"page": 1, "raw_sha256": "aa", "cleaned_sha256": "bb"})
    sidecar.write_row(p, {"page": 2, "raw_sha256": "cc", "cleaned_sha256": "dd"})
    lines = [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert lines[0]["page"] == 1
    assert lines[1]["page"] == 2


def test_write_row_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deeply" / "nested" / "qc.jsonl"
    sidecar.write_row(nested, {"page": 1, "raw_sha256": "aa"})
    assert nested.exists()


# --- should_skip_qc — 4-tuple idempotency --------------------------------


def _row(**overrides):
    base = {
        "raw_sha256": "raw_x",
        "cleaned_sha256": "cleaned_x",
        "judge_model_id": "claude-sonnet-4-6",
        "judge_prompt_sha256": "prompt_x",
    }
    base.update(overrides)
    return base


def test_should_skip_qc_true_when_all_four_match() -> None:
    existing = _row()
    assert sidecar.should_skip_qc(
        existing,
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
    )


def test_should_skip_qc_false_on_raw_change() -> None:
    assert not sidecar.should_skip_qc(
        _row(),
        raw_sha256="raw_DIFFERENT",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
    )


def test_should_skip_qc_false_on_cleaned_change() -> None:
    """If the cleanup pass re-cleaned a page (different cleaned_sha), the
    judge must re-grade — even on the same raw input."""
    assert not sidecar.should_skip_qc(
        _row(),
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_NEW",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
    )


def test_should_skip_qc_false_on_judge_model_change() -> None:
    assert not sidecar.should_skip_qc(
        _row(),
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-haiku-4-5",  # different
        judge_prompt_sha256="prompt_x",
    )


def test_should_skip_qc_false_on_prompt_change() -> None:
    assert not sidecar.should_skip_qc(
        _row(),
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_NEW",
    )


def test_should_skip_qc_false_on_missing_keys() -> None:
    """A row missing any of the 4 sha/id fields is un-skippable —
    don't risk a false skip from a legacy / partial-write row."""
    assert not sidecar.should_skip_qc(
        {"raw_sha256": "raw_x"},  # missing other 3
        raw_sha256="raw_x",
        cleaned_sha256="cleaned_x",
        judge_model_id="claude-sonnet-4-6",
        judge_prompt_sha256="prompt_x",
    )
