"""Round 2 schema consistency: the schema doc is the single source of truth."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.era_bucketing import bucket, build_output, classify_rows
from pursue_index.file_counts import file_key
from pursue_index.ntrs_claims_load import load_ntrs_claims, resolve_ntrs_claims
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim

_REPO = Path(__file__).resolve().parents[2]
_DOC = (_REPO / "docs" / "provenance-artifacts-schema.md").read_text()
_AMBIGUOUS = "ntrs_claims_migration_ambiguous_count"
_F1 = "a0a0a0a0a0a0a012"
_F2 = "b0b0b0b0b0b0b012"


def _row(card_id: str, title: str, **fields: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **fields}


def _stored(card_id: str, **extra: Any) -> dict[str, Any]:
    claim = ResolvedClaim(
        card_id=card_id,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    ).to_dict()
    claim.pop("row_key")
    return {**claim, **extra}


def _load(claims: list[dict[str, Any]], cards: list[dict[str, Any]]):
    return load_ntrs_claims({"schema": "ntrs-claims/v1", "csv_sha256": "a" * 64, "claims": claims}, cards)


# --- item 1: the per-file and per-row era maps carry the same keys ---------------


def test_era_file_and_row_counts_have_identical_key_sets() -> None:
    cards = [_row("aaaa", "A1", incident_date="2022-05-06"), _row("aaaa", "A2"), _row("bbbb", "B1")]
    out = build_output({"cards": cards}, bucket({"cards": cards}))
    assert set(out["era_row_counts"]) == set(out["era_file_counts"])
    assert "mixed" not in out["era_row_counts"] and "mixed" not in out["era_file_counts"]


def test_era_row_counts_still_sum_to_the_row_count() -> None:
    cards = [_row("aaaa", "A1", incident_date="2022-05-06"), _row("aaaa", "A2")]
    out = build_output({"cards": cards}, bucket({"cards": cards}))
    assert sum(out["era_row_counts"].values()) == out["card_row_count"] == 2


# --- item 2: file_count is distinct file_key() values ----------------------------


def test_file_count_is_the_number_of_distinct_file_keys() -> None:
    cards = [_row("aaaa", "A1"), _row("aaaa", "A2"), _row("", "N1"), _row("", "N2"), _row("bbbb", "B1")]
    result = bucket({"cards": cards})
    distinct = {file_key(c) for c in classify_rows(cards)}
    assert len(distinct) == 4
    assert result.file_count == len(distinct)
    assert build_report({"cards": cards}).file_count == len(distinct)


def test_the_doc_states_the_file_identity_rule_as_the_code_implements_it() -> None:
    assert "distinct `card_id`s" not in _DOC
    assert "a file is identified by its `card_id`" in _DOC
    assert "no `card_id`" in _DOC and "file_key()" in _DOC


# --- item 3: ntrs_claims_applied_row_count counts distinct rows ------------------


def test_the_applied_count_is_distinct_rows_reached_by_a_fanned_out_claim() -> None:
    cards = [_row(_F1, "N1"), _row(_F1, "N2"), _row(_F2, "N3")]
    fanned = _load([_stored(_F1)], cards).claims
    assert len(fanned) == 2
    second = _load([_stored(_F1, identifier_value="19700009999")], cards).claims
    extra = [*fanned, second[0]]  # a second claim on a row the first already reaches
    out = build_report({"cards": cards}, extra_claims=extra).to_dict()
    assert len(extra) == 3
    assert out["ntrs_claims_applied_row_count"] == 2


def test_a_claim_naming_no_manifest_row_is_not_an_applied_row() -> None:
    cards = [_row(_F1, "N1")]
    stray = ResolvedClaim.from_dict({**_stored(_F1), "row_key": f"{_F2}#0"})
    out = build_report({"cards": cards}, extra_claims=[stray]).to_dict()
    assert out["ntrs_claims_applied_row_count"] == 0


def test_the_doc_defines_the_applied_count_as_rows() -> None:
    line = next(ln for ln in _DOC.splitlines() if ln.startswith("| (new) | `ntrs_claims_applied_row_count`"))
    assert line.split("|")[3].strip() == "row"


# --- item 4: the legacy migration fails closed -----------------------------------


def test_a_legacy_claim_fans_out_to_its_own_file_only_and_is_labelled() -> None:
    cards = [_row(_F1, "N1", asset_url="u1"), _row(_F1, "N2", asset_url="u1"), _row(_F2, "N3", asset_url="u2")]
    loaded = _load([_stored(_F1)], cards)
    assert [c.row_key for c in loaded.claims] == [f"{_F1}#0", f"{_F1}#1"]
    assert {c.row_key_migrated_from for c in loaded.claims} == {"card_id"}
    assert loaded.migration_ambiguous == 0


def test_a_card_id_whose_rows_name_two_assets_applies_nothing_and_is_counted() -> None:
    cards = [_row(_F1, "N1", asset_url="u1"), _row(_F1, "N2", asset_url="u2")]
    loaded = _load([_stored(_F1)], cards)
    assert loaded.claims == []
    assert loaded.migration_ambiguous == 1


def test_a_claim_naming_one_of_two_assets_applies_to_that_asset_only() -> None:
    cards = [_row(_F1, "N1", asset_url="u1"), _row(_F1, "N2", asset_url="u2"), _row(_F1, "N3", asset_url="u2")]
    loaded = _load([_stored(_F1, asset_url="u2")], cards)
    assert [c.row_key for c in loaded.claims] == [f"{_F1}#1", f"{_F1}#2"]
    assert loaded.migration_ambiguous == 0


def test_a_claim_naming_an_asset_no_row_has_applies_nothing_and_is_counted() -> None:
    cards = [_row(_F1, "N1", asset_url="u1"), _row(_F1, "N2", asset_url="u1")]
    loaded = _load([_stored(_F1, asset_url="u9")], cards)
    assert loaded.claims == [] and loaded.migration_ambiguous == 1


def test_the_ambiguous_count_reaches_both_outputs(tmp_path: Path) -> None:
    cards = [_row(_F1, "N1", asset_url="u1"), _row(_F1, "N2", asset_url="u2")]
    (tmp_path / "data" / "provenance").mkdir(parents=True)
    stored = {"schema": "ntrs-claims/v1", "csv_sha256": "a" * 64, "claims": [_stored(_F1)]}
    (tmp_path / "data" / "provenance" / "ntrs-claims.json").write_text(json.dumps(stored))
    outcome = resolve_ntrs_claims(tmp_path, {"cards": cards, "csv_sha256": "a" * 64})
    assert outcome.summary_fields()[_AMBIGUOUS] == 1
    assert outcome.claims == []


def test_the_doc_documents_the_ambiguous_counter() -> None:
    assert _AMBIGUOUS in _DOC
