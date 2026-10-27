"""``scripts/_tranche_ready_supersedes.py`` -- what a record subsumes.

Only shas the stale-edge guard saw between the prior promoted manifest and
this record's sha are candidates, and each is listed only with a reason the
evidence supports: its rows are a strict subset of the new manifest
(``subset-of-current``), or it has its own record (``replaced-by-newer``).
The 096ef replay covers the Release-7 flap (7c3c..., subset-of-current).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.support.tranche_096ef import REPO_ROOT

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _tranche_ready_supersedes import derive_supersedes

_PRIOR, _MID, _NEW, _LATER = ("1" * 64, "2" * 64, "3" * 64, "4" * 64)


def _state(tmp: Path, seen: list[str]) -> Path:
    path = tmp / "poll-state.json"
    path.write_text(json.dumps({"current_sha": seen[-1], "seen": seen}))
    return path


def _run(tmp: Path, seen: list[str], *, mid_csv: bool, mid_record: bool) -> list[dict]:
    archive, ready = tmp / "csv", tmp / "ready"
    archive.mkdir()
    ready.mkdir()
    if mid_csv:
        (archive / f"{_MID}.csv").write_bytes(b"not,a,subset\r\n")
    if mid_record:
        (ready / f"{_MID[:12]}.json").write_text("{}")
    return derive_supersedes(_state(tmp, seen), archive, _PRIOR, _NEW,
                             tmp / "absent-manifest.json", ready)


def test_an_intermediate_sha_with_its_own_record_was_replaced_by_newer(tmp_path: Path) -> None:
    assert _run(tmp_path, [_PRIOR, _MID, _NEW], mid_csv=True, mid_record=True) == [
        {"tranche_sha256": _MID, "tranche_sha12": _MID[:12], "issue": None,
         "reason": "replaced-by-newer"}]


def test_an_intermediate_sha_without_evidence_is_left_out(tmp_path: Path) -> None:
    assert _run(tmp_path, [_PRIOR, _MID, _NEW], mid_csv=True, mid_record=False) == []
    other = tmp_path / "no-csv"
    other.mkdir()
    assert _run(other, [_PRIOR, _MID, _NEW], mid_csv=False, mid_record=True) == []


def test_only_shas_between_the_prior_manifest_and_this_sha_count(tmp_path: Path) -> None:
    assert _run(tmp_path, [_MID, _PRIOR, _NEW, _LATER], mid_csv=True, mid_record=True) == []
    missing_state = derive_supersedes(tmp_path / "nope.json", tmp_path, _PRIOR, _NEW,
                                      tmp_path / "m.json", tmp_path)
    assert missing_state == []
