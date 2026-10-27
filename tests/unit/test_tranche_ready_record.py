"""``pursue_index.tranche_ready.record`` -- assembling the whole record.

Status follows the hand-off spec (pursue-opsec ``tranche-handoff.md`` §2):
``ready`` only when every candidate has a verdict and no stop, and the page
count is complete; otherwise ``stop-and-ask`` with one ``stop_reasons``
entry per cause. Scope is the R7C.1 worklist (``ingest_scope``) as data,
with a candidate recommended for a rename scoped as ``renamed``.
"""

from __future__ import annotations

import copy

from pursue_index.release import rates
from pursue_index.tranche_ready.record import RecordInputs, build_record
from pursue_index.tranche_ready.schema import load_schema, validate

SHA_NEW, SHA_OLD = "a" * 64, "b" * 64
OLD_ID, NEW_ID, N1, N2 = "a0f6663169c21caf", "ff3939f95d878062", "1" * 16, "2" * 16


def _manifest(sha: str, cards: list[tuple[str, str]]) -> dict:
    return {"csv_sha256": sha, "cards": [{"card_id": c, "title": t} for c, t in cards]}


_DIFF = {
    "tranche_sha256": SHA_NEW, "prior_manifest_sha": SHA_OLD,
    "summary": {"renames_confirmed": 0, "new_content": 2, "quarantined": 1,
                "restored_unchanged": 0, "restored_modified": 0, "restored_unknown": 0,
                "removed": 1, "field_only_changes": 3, "row_changes": 0},
    "renames_confirmed": [],
    "new_content": [{"new_card_id": N1, "asset_filename": "x.pdf"},
                    {"new_card_id": N2, "asset_filename": "y.pdf"}],
    "quarantined": [{"new_card_id": NEW_ID, "new_asset_filename": "d.pdf"}],
}
_CANDIDATE = {
    "kind": "quarantine", "new_card_id": NEW_ID, "old_card_id": OLD_ID,
    "old_byte_sha256": "c" * 64, "new_byte_sha256": "d" * 64, "old_byte_size": 1,
    "new_byte_size": 2, "byte_verdict": "metadata-only", "byte_verdict_reason": None,
    "evidence": {"old_prefix_of_new": True, "appended_bytes": 1, "incremental_update": True},
    "stop_and_ask": False, "recommended_disposition": "approve-rename-metadata-only-resave",
}


def _inputs(**over) -> RecordInputs:
    base = dict(
        old_manifest=_manifest(SHA_OLD, [(OLD_ID, "DOW-UAP-D042, Japan")]),
        new_manifest=_manifest(SHA_NEW, [(N1, "DOW-UAP-D155, X"), (N2, "FBI-UAP-D043, Y"),
                                         (NEW_ID, "DOW-UAP-D042, Arabian Gulf"), (NEW_ID, "")]),
        diff=copy.deepcopy(_DIFF), candidates=[dict(_CANDIDATE)],
        page_counts={N1: 5, N2: 50, NEW_ID: 1}, new_fallback_ids=[], old_fetched=1,
        old_failures=[], judge=rates.JudgeRate(0.0165, rates.JUDGE_METERED),
        tranche_issue=177, supersedes=[], generated_by={"tool": "t", "version": "v"},
        generated_at="2026-10-24T03:02:00+00:00",
    )
    return RecordInputs(**{**base, **over})


def test_a_resolved_fully_counted_tranche_is_ready_and_valid() -> None:
    record = build_record(_inputs())
    assert validate(record, load_schema()) == []
    assert record["status"] == "ready" and "stop_reasons" not in record
    assert (record["tranche_sha256"], record["tranche_sha12"]) == (SHA_NEW, SHA_NEW[:12])
    assert record["detected_at"] == record["generated_at"]
    assert record["manifest"] == {"old_row_count": 1, "new_row_count": 4,
                                  "prior_manifest_sha256": SHA_OLD, "new_snapshot_sha256": SHA_NEW}
    assert record["diff"]["new_content"] == 2 and record["diff"]["field_only_changes"] == 3
    assert record["scope"] == {"card_count": 3, "cards": [
        {"card_id": N1, "reason": "new", "doc_id": "DOW-UAP-D155"},
        {"card_id": N2, "reason": "new", "doc_id": "FBI-UAP-D043"},
        {"card_id": NEW_ID, "reason": "renamed", "doc_id": "DOW-UAP-D042"}]}
    assert record["pages"]["total"] == 56 and record["pages"]["source"] == "fetched"
    assert [p["card_id"] for p in record["pages"]["largest"]] == [N2, N1, NEW_ID]
    assert record["fetch"] == {"new_fetched": 3, "new_failed": 0, "old_fetched": 1,
                               "old_failed": 0, "failures": []}


def test_a_null_verdict_makes_it_stop_and_ask_naming_the_card() -> None:
    cand = {**_CANDIDATE, "byte_verdict": None, "byte_verdict_reason": "old_fetch_failed",
            "evidence": None, "stop_and_ask": True, "old_byte_sha256": None,
            "old_byte_size": None, "recommended_disposition": "operator-rule-required"}
    record = build_record(_inputs(candidates=[cand], old_fetched=0,
                                  old_failures=[(OLD_ID, "old_fetch_failed")]))
    assert validate(record, load_schema()) == []
    assert record["status"] == "stop-and-ask"
    assert any(NEW_ID in r and "old_fetch_failed" in r for r in record["stop_reasons"])
    assert record["fetch"]["failures"] == [
        {"card_id": OLD_ID, "side": "old", "reason": "old_fetch_failed"}]
    assert {"card_id": NEW_ID, "reason": "quarantined-new", "doc_id": "DOW-UAP-D042"} in (
        record["scope"]["cards"])


def test_a_partial_page_count_makes_it_stop_and_ask() -> None:
    record = build_record(_inputs(page_counts={N1: 5, NEW_ID: 1}, new_fallback_ids=[N2]))
    assert validate(record, load_schema()) == []
    assert record["status"] == "stop-and-ask"
    assert record["pages"]["source"] == "partial" and record["estimate"]["partial"] is True
    assert record["estimate"]["fallback_cards"] == [N2]
    assert {"card_id": N2, "side": "new", "reason": "new_fetch_failed"} in (
        record["fetch"]["failures"])
    assert any("partial" in r for r in record["stop_reasons"])


def test_moved_resaves_count_as_renames_since_the_schema_has_no_such_bucket() -> None:
    diff = copy.deepcopy(_DIFF)
    diff["summary"]["renames_metadata_only"] = 1
    record = build_record(_inputs(diff=diff))
    assert record["diff"]["renames_confirmed"] == 1
    assert validate(record, load_schema()) == []
