"""An auto-approved re-save leaves a reviewable audit row.

The alias row (``data/card-aliases.json``) already names the classifier
verdict (``change_nature``) and both byte hashes; it also names WHICH parser
produced that verdict (``classifier``: pypdf version + a hash of the parser
sources), so a later parser bug can be traced to every alias it approved.
"""

from __future__ import annotations

import re

from pursue_index import classifier_id
from pursue_index.alias_schema import alias_row_errors
from pursue_index.ingest import auto_approve_renames
from pursue_index.tranche_resave import RESAVE_BUCKET, demote_resaves

OLD_ID, NEW_ID = "a0f6663169c21caf", "ff3939f95d878062"


def _quarantined() -> dict:
    row = {"new_card_id": NEW_ID, "new_byte_sha256": "ca" * 32, "matched_against": [OLD_ID],
           "matches": [{"card_id": OLD_ID, "reasons": ["title"]}]}
    return {"quarantined": [row]}


def test_classifier_id_names_pypdf_and_a_source_hash() -> None:
    assert re.fullmatch(r"pdf-update-parser/pypdf[\w.]+/[0-9a-f]{12}", classifier_id.classifier_id())


def test_classifier_id_changes_when_a_parser_source_changes(monkeypatch, tmp_path) -> None:
    before = classifier_id.classifier_id()
    fake = tmp_path / "pdf_update.py"
    fake.write_text("# edited parser\n")
    classifier_id.classifier_id.cache_clear()
    monkeypatch.setattr(classifier_id, "_SOURCES", (fake,))
    try:
        assert classifier_id.classifier_id() != before
    finally:
        classifier_id.classifier_id.cache_clear()


def test_demoted_row_carries_the_classifier_id() -> None:
    buckets = _quarantined()
    demote_resaves(buckets, lambda old_id, new_sha: "d5" * 32, set())
    assert buckets[RESAVE_BUCKET][0]["classifier"] == classifier_id.classifier_id()


def test_alias_row_records_verdict_hashes_and_classifier() -> None:
    buckets = _quarantined()
    demote_resaves(buckets, lambda old_id, new_sha: "d5" * 32, set())
    [alias] = auto_approve_renames(buckets)
    assert alias["change_nature"] == "metadata-only"
    assert (alias["old_byte_sha256"], alias["new_byte_sha256"]) == ("d5" * 32, "ca" * 32)
    assert alias["classifier"] == classifier_id.classifier_id()


def test_schema_accepts_and_checks_the_classifier_field() -> None:
    row = {"old_card_id": OLD_ID, "new_card_id": NEW_ID, "method": "metadata-only-resave",
           "established": "2026-10-26"}
    assert alias_row_errors({**row, "classifier": "pdf-update-parser/pypdf6/abc"}) == []
    assert alias_row_errors({**row, "classifier": ""}) != []
