"""Every provenance artifact whose keys or meaning changed carries a v2 schema id,
and a schema doc lists every renamed, added or re-semanticized key."""

from __future__ import annotations

import json
from pathlib import Path

import pursue_index.era_bucketing as era_bucketing
import pursue_index.identifier_resolver as identifier_resolver
import pursue_index.ntrs_source as ntrs_source
import pursue_index.tier0_sweep as tier0_sweep

_REPO = Path(__file__).resolve().parents[2]
_DOC = _REPO / "docs" / "provenance-artifacts-schema.md"
_ARTIFACTS = {
    "era-buckets.json": ("era-agency-buckets/v2", era_bucketing._SCHEMA),
    "identifier-claims.json": ("identifier-resolver-claims/v2", identifier_resolver._SCHEMA),
    "tier0-manifest-claims.json": ("tier0-manifest-provenance/v2", tier0_sweep._SCHEMA),
    "ntrs-claims.json": ("ntrs-claims/v2", ntrs_source.SCHEMA),
}


def test_every_writer_declares_its_v2_schema_id() -> None:
    for name, (expected, declared) in _ARTIFACTS.items():
        assert declared == expected, name


def test_every_committed_artifact_carries_its_v2_schema_id() -> None:
    for name, (expected, _) in _ARTIFACTS.items():
        stored = json.loads((_REPO / "data" / "provenance" / name).read_text())
        assert stored["schema"] == expected, name


def test_the_ntrs_loader_still_reads_a_v1_file() -> None:
    from pursue_index.ntrs_claims_load import load_ntrs_claims

    loaded = load_ntrs_claims({"schema": "ntrs-claims/v1", "csv_sha256": "a" * 64, "claims": []})
    assert loaded.claims == [] and loaded.refused_claims == 0


_REQUIRED_TERMS = (
    "row_key",
    "card_id",
    "not unique",
    "no_prior_release_rows",
    "no_prior_release_files",
    "no_prior_release_file_count",
    "no_prior_release_row_count",
    "era_reconciled_from",
    "reconciled_from_sibling",
    "file_route_counts",
    "row_route_counts",
    "partially_resolved_file_count",
    "partially_resolved_files",
    "reconciliation_4a",
    "unit",
    "claims_without_row_key",
    "row_key_migrated_from",
    "card_row_count",
    "file_count",
    "era_file_counts",
    "era_row_counts",
    "agency_row_counts",
    "superseded_by_claim_row_count",
    "undated_triage_row_count",
    "unresolved_files",
    "unresolved_row_count",
    "unresolved_rows",
    "page_image_flagged_files",
    "ntrs_claims_applied_row_count",
    "row_counts",
    "era-agency-buckets/v2",
    "identifier-resolver-claims/v2",
    "tier0-manifest-provenance/v2",
    "ntrs-claims/v2",
)


def test_the_schema_doc_lists_every_renamed_added_or_resemanticized_key() -> None:
    text = _DOC.read_text()
    missing = [term for term in _REQUIRED_TERMS if term not in text]
    assert not missing, f"docs/provenance-artifacts-schema.md does not mention {missing}"


def test_the_schema_doc_names_each_old_key_it_replaces() -> None:
    text = _DOC.read_text()
    for old in ("card_count", "agency_counts", "no_prior_release", "superseded_by_claim_count", "undated_triage_count"):
        assert f"`{old}`" in text, old
