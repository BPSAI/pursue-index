"""Upstream-controlled text and counts are clamped to the vendored schema bounds.

One oversized upstream field must not make the whole record invalid (exit 4,
nothing committed): the producer clamps before validation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pursue_index.tranche_ready.candidates import CandidateRow, build_candidate
from pursue_index.tranche_ready.old_bytes import StagedBytes
from pursue_index.tranche_ready.record import _stop_reasons
from pursue_index.tranche_ready.scope import _doc_id


def _side(tmp_path: Path) -> StagedBytes:
    path = tmp_path / "a.pdf"
    path.write_bytes(b"x")
    return StagedBytes(path=path, sha256=hashlib.sha256(b"x").hexdigest(), size=1)


def test_candidate_text_is_clamped_to_the_schema_bounds(tmp_path: Path) -> None:
    row = CandidateRow("rename-candidate", "n" * 16, "o" * 16, {
        "new_title": "N" * 600, "continuity_reasons": ["r" * 300] * 60})
    side = _side(tmp_path)
    cand = build_candidate(row, old_title="O" * 600, old_side=side, new_side=side)
    assert len(cand["new_title"]) == len(cand["old_title"]) == 512
    assert len(cand["continuity_signals"]) == 50
    assert all(len(s) == 256 for s in cand["continuity_signals"])


def test_in_bound_candidate_text_is_untouched(tmp_path: Path) -> None:
    row = CandidateRow("rename-candidate", "n" * 16, "o" * 16, {
        "new_title": "N" * 512, "continuity_reasons": ["a", "b"]})
    side = _side(tmp_path)
    cand = build_candidate(row, old_title="O" * 512, old_side=side, new_side=side)
    assert cand["new_title"] == "N" * 512 and cand["old_title"] == "O" * 512
    assert cand["continuity_signals"] == ["a", "b"]


def test_an_overlong_doc_id_is_dropped_not_emitted() -> None:
    assert _doc_id("DOW-" + "A" * 61 + ", title") is None
    assert _doc_id("DOW-" + "A" * 60 + ", title") == "DOW-" + "A" * 60
    assert _doc_id("DOW-UAP-D176, title") == "DOW-UAP-D176"


def test_stop_reasons_are_capped_with_a_summary_reason() -> None:
    cands = [{"new_card_id": f"{i:016x}", "byte_verdict": None, "byte_verdict_reason": "r",
              "stop_and_ask": True, "kind": "quarantine"} for i in range(250)]
    reasons = _stop_reasons(cands, [])
    assert len(reasons) == 200
    assert "51 more" in reasons[-1]
    assert reasons[0].startswith("0000000000000000:")
