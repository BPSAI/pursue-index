"""Tests for the post-ingest TOCTOU audit (plan step 5).

Between when `tranche_diff` recorded a byte_sha for a candidate rename
and when `pursue ingest approve` runs, upstream could in principle
serve different bytes — turning a confirmed Class A rename or a
restored_unchanged event into a content swap done under cover of
metadata change. The audit re-fetches the upstream bytes at approval
time and compares against the recorded sha. Any mismatch refuses the
approval before aliases are materialized.

The audit is a pure-function over (audit targets, fetcher); no
network is touched by these tests — the fetcher is injected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.post_ingest_audit import (  # noqa: E402
    audit_targets,
    collect_audit_targets,
)


# --- audit_targets (the verification loop) ---


def test_audit_ok_when_fetched_sha_matches_expected() -> None:
    targets = [
        {"card_id": "aa11", "kind": "byte_collision_rename",
         "asset_url": "https://x/a.pdf", "expected_sha": "ff" * 32},
    ]
    fake = {"https://x/a.pdf": "ff" * 32}
    results = audit_targets(targets, fetch_byte_sha=lambda u: fake.get(u))
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["card_id"] == "aa11"


def test_audit_detects_mismatch() -> None:
    targets = [
        {"card_id": "aa11", "kind": "byte_collision_rename",
         "asset_url": "https://x/a.pdf", "expected_sha": "ff" * 32},
    ]
    fake = {"https://x/a.pdf": "ee" * 32}  # different bytes
    results = audit_targets(targets, fetch_byte_sha=lambda u: fake.get(u))
    assert results[0]["status"] == "mismatch"
    assert results[0]["expected_sha"] == "ff" * 32
    assert results[0]["actual_sha"] == "ee" * 32


def test_audit_detects_fetch_failure() -> None:
    targets = [
        {"card_id": "aa11", "kind": "byte_collision_rename",
         "asset_url": "https://x/a.pdf", "expected_sha": "ff" * 32},
    ]
    results = audit_targets(targets, fetch_byte_sha=lambda u: None)
    assert results[0]["status"] == "fetch_failed"


def test_audit_skips_targets_without_asset_url() -> None:
    """operator_manual aliases on VID/metadata-only cards have no
    asset_url to audit. Skip with a note; do NOT fail the audit."""
    targets = [
        {"card_id": "vid1", "kind": "operator_manual_rename",
         "asset_url": None, "expected_sha": None},
    ]
    results = audit_targets(targets, fetch_byte_sha=lambda u: None)
    assert results[0]["status"] == "skipped"
    assert "no asset_url" in results[0]["note"].lower()


def test_audit_handles_multiple_targets_mixed_outcomes() -> None:
    targets = [
        {"card_id": "ok1", "kind": "byte_collision_rename",
         "asset_url": "https://x/ok.pdf", "expected_sha": "aa" * 32},
        {"card_id": "bad1", "kind": "restored_unchanged",
         "asset_url": "https://x/bad.pdf", "expected_sha": "bb" * 32},
        {"card_id": "skip1", "kind": "operator_manual_rename",
         "asset_url": None, "expected_sha": None},
    ]
    fake = {
        "https://x/ok.pdf": "aa" * 32,
        "https://x/bad.pdf": "cc" * 32,  # mismatch
    }
    results = audit_targets(targets, fetch_byte_sha=lambda u: fake.get(u))
    statuses = {r["card_id"]: r["status"] for r in results}
    assert statuses == {"ok1": "ok", "bad1": "mismatch", "skip1": "skipped"}


# --- collect_audit_targets (build targets from approval + diff) ---


def test_collect_includes_byte_collision_renames() -> None:
    enriched_aliases = [
        {"new_card_id": "aa11", "old_card_id": "old1", "method": "byte_collision",
         "byte_sha256": "ff" * 32},
    ]
    new_manifest = {"cards": [
        {"card_id": "aa11", "asset_url": "https://x/new.pdf"},
    ]}
    diff = {"restored_unchanged": []}
    targets = collect_audit_targets(enriched_aliases, diff, new_manifest)
    assert len(targets) == 1
    assert targets[0]["card_id"] == "aa11"
    assert targets[0]["kind"] == "byte_collision_rename"
    assert targets[0]["expected_sha"] == "ff" * 32
    assert targets[0]["asset_url"] == "https://x/new.pdf"


def test_collect_includes_restored_unchanged() -> None:
    enriched_aliases = []
    new_manifest = {"cards": []}
    diff = {
        "restored_unchanged": [
            {"new_card_id": "rest1", "new_asset_url": "https://x/r.pdf",
             "pinned_byte_sha256": "dd" * 32},
        ],
    }
    targets = collect_audit_targets(enriched_aliases, diff, new_manifest)
    assert len(targets) == 1
    assert targets[0]["card_id"] == "rest1"
    assert targets[0]["kind"] == "restored_unchanged"
    assert targets[0]["expected_sha"] == "dd" * 32


def test_collect_marks_operator_manual_for_skip_when_no_url() -> None:
    enriched_aliases = [
        {"new_card_id": "vid1", "old_card_id": "old1", "method": "operator_manual"},
    ]
    new_manifest = {"cards": [
        {"card_id": "vid1", "asset_url": None},
    ]}
    diff = {"restored_unchanged": []}
    targets = collect_audit_targets(enriched_aliases, diff, new_manifest)
    assert len(targets) == 1
    assert targets[0]["kind"] == "operator_manual_rename"
    assert targets[0]["asset_url"] is None
    assert targets[0]["expected_sha"] is None


def test_collect_handles_empty_inputs() -> None:
    targets = collect_audit_targets([], {"restored_unchanged": []}, {"cards": []})
    assert targets == []
