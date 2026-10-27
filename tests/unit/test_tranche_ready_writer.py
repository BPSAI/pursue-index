"""``pursue_index.tranche_ready.writer`` -- validate before write, append-only.

The producer-side guard: a record that does not validate against the
vendored schema is never written, and the error names the failing field.
Records are append-only per sha, mirroring ``poll_snapshot.py``'s diff
records (#157): an equal recompute is a no-op, a disagreeing one is refused
with both versions printed. "Equal" ignores only when-and-by-what
provenance (``detected_at``, ``generated_at``, ``generated_by``), which a
re-run necessarily changes; every other field is content.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pursue_index.tranche_ready.writer import (
    AppendOnlyError,
    InvalidRecordError,
    check_record,
    write_record,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json").read_text())


@pytest.fixture
def record() -> dict:
    out = copy.deepcopy(VECTOR)
    del out["example_provenance"]
    return out


def test_a_record_missing_a_required_field_is_refused_naming_it(
    tmp_path: Path, record: dict,
) -> None:
    del record["estimate"]
    path = tmp_path / "tranche-ready" / "096ef2c0058a.json"
    with pytest.raises(InvalidRecordError) as excinfo:
        write_record(path, record)
    assert excinfo.value.field == "estimate"
    assert "estimate" in str(excinfo.value)
    assert not path.exists() and not path.parent.exists()


def test_a_valid_record_is_written(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "tranche-ready" / "096ef2c0058a.json"
    assert write_record(path, record) == "written"
    assert json.loads(path.read_text()) == record
    assert path.read_text().endswith("}\n")
    check_record(record)  # no raise


def test_an_equal_recompute_is_a_no_op_even_with_new_timestamps(
    tmp_path: Path, record: dict,
) -> None:
    path = tmp_path / "096ef2c0058a.json"
    write_record(path, record)
    before = path.read_bytes()
    rerun = {**record, "generated_at": "2026-10-25T00:00:00+00:00",
             "generated_by": {**record["generated_by"], "poll_run_id": 42}}
    assert write_record(path, rerun) == "unchanged"
    assert path.read_bytes() == before


def test_a_disagreeing_recompute_is_refused_and_writes_nothing(
    tmp_path: Path, record: dict,
) -> None:
    path = tmp_path / "096ef2c0058a.json"
    write_record(path, record)
    before = path.read_bytes()
    rerun = copy.deepcopy(record)
    rerun["candidates"][0]["byte_verdict"] = None
    with pytest.raises(AppendOnlyError) as excinfo:
        write_record(path, rerun)
    message = str(excinfo.value)
    assert "append-only" in message and str(path) in message
    assert "stored:" in message and "recomputed:" in message
    assert path.read_bytes() == before


def test_an_invalid_record_is_refused_before_the_append_only_check(
    tmp_path: Path, record: dict,
) -> None:
    path = tmp_path / "096ef2c0058a.json"
    write_record(path, record)
    broken = {**record, "status": "maybe"}
    with pytest.raises(InvalidRecordError, match="status"):
        write_record(path, broken)
