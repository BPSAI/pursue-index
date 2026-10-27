"""A refusal body (public issue) never carries record free text."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pursue_index.tranche_ready import refusal
from pursue_index.tranche_ready.writer import AppendOnlyError, write_record

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json").read_text())
HOSTILE = "```\n@someone <script>[x](https://evil.invalid)"


@pytest.fixture
def record() -> dict:
    out = copy.deepcopy(VECTOR)
    del out["example_provenance"]
    return out


def _conflict(tmp_path: Path, record: dict, new_title: str) -> AppendOnlyError:
    path = tmp_path / "096ef2c0058a.json"
    write_record(path, record)
    rerun = copy.deepcopy(record)
    rerun["candidates"][0]["new_title"] = new_title
    with pytest.raises(AppendOnlyError) as info:
        write_record(path, rerun)
    return info.value


def test_hostile_title_text_never_reaches_the_message(tmp_path: Path, record: dict) -> None:
    message = str(_conflict(tmp_path, record, HOSTILE))
    for bad in ("```", "@someone", "<", ">", "`", "evil.invalid", "script"):
        assert bad not in message
    assert len(message.encode()) < refusal.MAX_BODY_BYTES
    assert "candidates/0/new_title" in message


def test_message_reports_paths_hashes_and_sizes(tmp_path: Path, record: dict) -> None:
    err = _conflict(tmp_path, record, "other title")
    assert "sha256=" in str(err) and "bytes=" in str(err)
    assert "stored:" in str(err) and "recomputed:" in str(err)


def test_oversized_records_still_yield_a_body_under_the_cap(tmp_path: Path, record: dict) -> None:
    record["candidates"][0]["continuity_signals"] = ["s"] * 5
    path = tmp_path / "096ef2c0058a.json"
    write_record(path, record)
    stored = json.loads(path.read_text())
    rerun = copy.deepcopy(stored)
    rerun["extra_" + "k" * 100] = 1
    rerun["candidates"][0]["new_title"] = "T" * 500
    rerun["candidates"] += [copy.deepcopy(rerun["candidates"][0]) for _ in range(2000)]
    text = refusal.describe_conflict(path, stored, rerun)
    assert len(text.encode()) <= refusal.MAX_BODY_BYTES


def test_neutralize_strips_markup_and_mentions() -> None:
    out = refusal.neutralize("a `b` <c> @d")
    assert "`" not in out and "<" not in out and ">" not in out and "@" not in out
    assert "\uff20d" in out


def test_cap_bounds_the_body() -> None:
    assert len(refusal.cap("x" * 100_000).encode()) <= refusal.MAX_BODY_BYTES


def test_full_diff_keeps_the_text_for_the_local_file(tmp_path: Path, record: dict) -> None:
    err = _conflict(tmp_path, record, HOSTILE)
    assert "evil.invalid" in err.full_diff()
