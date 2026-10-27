"""``pursue_index.tranche_ready.candidates`` -- one candidate per diff row.

Every rename (Class A, or a metadata-only re-save moved out of quarantine)
and every quarantine (Class C) row of the tranche diff becomes one record
candidate. Its ``byte_verdict`` is ``classify_bytes`` on the two staged
files; when either side is missing (unreachable, or not the registry's
bytes) the verdict is null, the reason names which side, and the candidate
forces stop-and-ask -- as does a quarantine whose bytes changed content.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pursue_index.tranche_ready.candidates import CandidateRow, build_candidate, candidate_rows
from pursue_index.tranche_ready.old_bytes import StagedBytes
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave

OLD_ID, NEW_ID = "a0f6663169c21caf", "ff3939f95d878062"
_QUARANTINED = {
    "new_card_id": NEW_ID, "new_title": "D042, Arabian Gulf", "new_byte_sha256": "c" * 64,
    "matched_against": [OLD_ID],
    "matches": [{"card_id": OLD_ID, "title": "D042, Japan", "reasons": ["matching numeric id 42"],
                 "strength": 1}],
}


def _staged(tmp_path: Path, name: str, data: bytes) -> StagedBytes:
    path = tmp_path / name
    path.write_bytes(data)
    return StagedBytes(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


@pytest.fixture
def d042(tmp_path: Path) -> tuple[StagedBytes, StagedBytes]:
    base = build_base_pdf()
    return _staged(tmp_path, "old.pdf", base.data), _staged(tmp_path, "new.pdf",
                                                             metadata_only_resave(base))


def test_rows_cover_renames_resaves_and_quarantines_in_that_order() -> None:
    diff = {
        "renames_confirmed": [{"old_card_id": "1" * 16, "new_card_id": "2" * 16}],
        "renames_metadata_only": [{"old_card_id": "3" * 16, "new_card_id": "4" * 16}],
        "quarantined": [_QUARANTINED, {**_QUARANTINED, "new_card_id": "5" * 16,
                                        "resave_evidence": {"old_card_id": "6" * 16}}],
        "new_content": [{"new_card_id": "7" * 16}],
    }
    assert [(r.kind, r.new_card_id, r.old_card_id) for r in candidate_rows(diff)] == [
        ("rename-candidate", "2" * 16, "1" * 16),
        ("rename-candidate", "4" * 16, "3" * 16),
        ("quarantine", NEW_ID, OLD_ID),
        ("quarantine", "5" * 16, "6" * 16),
    ]


def test_a_metadata_only_quarantine_recommends_the_resave_rename(d042) -> None:
    old, new = d042
    [row] = candidate_rows({"quarantined": [_QUARANTINED]})
    cand = build_candidate(row, old_title="D042, Japan", old_side=old, new_side=new)
    assert cand["byte_verdict"] == "metadata-only" and cand["byte_verdict_reason"] is None
    assert cand["stop_and_ask"] is False
    assert cand["recommended_disposition"] == "approve-rename-metadata-only-resave"
    assert cand["continuity_signals"] == ["matching numeric id 42"]
    assert (cand["old_byte_sha256"], cand["new_byte_sha256"]) == (old.sha256, new.sha256)
    assert cand["evidence"] == {"old_prefix_of_new": True, "appended_bytes": new.size - old.size,
                                "incremental_update": True}


def test_unreachable_old_bytes_null_the_verdict_and_stop(d042) -> None:
    _, new = d042
    [row] = candidate_rows({"quarantined": [_QUARANTINED]})
    failed = StagedBytes(path=None, failure="old_fetch_failed")
    cand = build_candidate(row, old_title="D042, Japan", old_side=failed, new_side=new)
    assert cand["byte_verdict"] is None and cand["evidence"] is None
    assert cand["byte_verdict_reason"] == "old_fetch_failed"
    assert cand["stop_and_ask"] is True
    assert cand["recommended_disposition"] == "operator-rule-required"
    assert cand["old_byte_sha256"] is None and cand["old_byte_size"] is None


def test_a_content_changed_quarantine_stops(tmp_path: Path, d042) -> None:
    old, _ = d042
    changed = _staged(tmp_path, "changed.pdf", build_base_pdf(b"(other) Tj").data)
    [row] = candidate_rows({"quarantined": [_QUARANTINED]})
    cand = build_candidate(row, old_title="D042, Japan", old_side=old, new_side=changed)
    assert cand["byte_verdict"] == "content-changed"
    assert (cand["stop_and_ask"], cand["recommended_disposition"]) == (
        True, "operator-rule-required")


def test_byte_identical_rename_is_metadata_only_without_classifying(d042) -> None:
    old, _ = d042
    row = CandidateRow("rename-candidate", NEW_ID, OLD_ID, {"new_title": "x"})

    def never(*a, **k):
        raise AssertionError("identical bytes need no classifier run")

    cand = build_candidate(row, old_title="y", old_side=old, new_side=old, classify=never)
    assert cand["byte_verdict"] == "metadata-only"
    assert cand["recommended_disposition"] == "approve-rename"
    assert cand["evidence"] == {"old_prefix_of_new": True, "appended_bytes": 0,
                                "incremental_update": False}
