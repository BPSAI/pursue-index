"""keep_unchanged_timestamp keeps generated_at only when the payload is unchanged."""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.release.stable_timestamp import keep_unchanged_timestamp

OLD = "2026-01-01T00:00:00+00:00"
NEW = "2026-02-02T00:00:00+00:00"


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload))


def test_unchanged_payload_keeps_the_old_timestamp(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    _write(out, {"ids": [1, 2], "generated_at": OLD})
    got = keep_unchanged_timestamp(out, {"ids": [1, 2], "generated_at": NEW})
    assert got == {"ids": [1, 2], "generated_at": OLD}


def test_changed_payload_takes_the_new_timestamp(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    _write(out, {"ids": [1], "generated_at": OLD})
    got = keep_unchanged_timestamp(out, {"ids": [1, 2], "generated_at": NEW})
    assert got["generated_at"] == NEW


def test_an_added_or_removed_key_counts_as_a_change(tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    _write(out, {"ids": [1], "extra": 0, "generated_at": OLD})
    assert keep_unchanged_timestamp(out, {"ids": [1], "generated_at": NEW})["generated_at"] == NEW


def test_missing_bad_or_unstamped_files_leave_the_payload_alone(tmp_path: Path) -> None:
    new = {"ids": [1], "generated_at": NEW}
    assert keep_unchanged_timestamp(tmp_path / "absent.json", new) == new
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert keep_unchanged_timestamp(bad, new) == new
    arr = tmp_path / "arr.json"
    _write(arr, [1])
    assert keep_unchanged_timestamp(arr, new) == new
    nostamp = tmp_path / "nostamp.json"
    _write(nostamp, {"ids": [1]})
    assert keep_unchanged_timestamp(nostamp, new) == new
