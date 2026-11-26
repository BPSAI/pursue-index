"""Claims and joins: unmatched legacy claims, one manifest revision per join, disjoint counts.

Fixtures only; nothing here touches the network or the stored artifacts beyond reading them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pursue_index.ntrs_claims_load import NtrsOutcome, load_ntrs_claims, resolve_ntrs_claims
from pursue_index.ntrs_source import run_searches
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report, classify
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from tests.support.ntrs_fakes import TODAY, Net, Resp, card, variant

_REPO = Path(__file__).resolve().parents[2]
_DOC = " ".join((_REPO / "docs" / "provenance-artifacts-schema.md").read_text().split())
_EARLY = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")


def _claim(card_id: str, row_key: str = "", source: ResolutionSource = ResolutionSource.NTRS_METADATA) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=card_id,
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=source,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def _raw(card_id: str, **over: Any) -> dict[str, Any]:
    """A stored claim; a legacy one (no ``row_key`` key at all) unless a ``row_key`` is passed."""
    stored = _claim(card_id).to_dict()
    stored.pop("row_key", None)
    return {**stored, **over}


def _row(card_id: str, title: str, **over: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "NASA", "release_date": "5/8/2026", **over}


def _stored(root: Path, claims: list[dict[str, Any]], sha: str = "a" * 64) -> None:
    out = root / "data" / "provenance"
    out.mkdir(parents=True)
    (out / "ntrs-claims.json").write_text(json.dumps({"schema": "ntrs-claims/v1", "csv_sha256": sha, "claims": claims}))


# --- 1: a legacy claim whose file is not in the manifest ------------------------


def test_a_legacy_claim_for_a_file_not_in_the_manifest_is_unmatched_not_unkeyed() -> None:
    cards = [_row("aaaaaaaaaaaaaaaa", "A")]
    loaded = load_ntrs_claims({"csv_sha256": "s", "claims": [_raw("bbbbbbbbbbbbbbbb")]}, cards)
    assert loaded.claims == []
    assert loaded.migration_unmatched == 1
    assert loaded.migration_ambiguous == 0


def test_the_unmatched_count_reaches_the_summary_and_the_report_counts_it_nowhere_else(tmp_path: Path) -> None:
    _stored(tmp_path, [_raw("bbbbbbbbbbbbbbbb")])
    manifest = {"csv_sha256": "a" * 64, "cards": [_row("aaaaaaaaaaaaaaaa", "A")]}
    outcome = resolve_ntrs_claims(tmp_path, manifest)
    assert outcome.summary_fields()["ntrs_migration_unmatched_claim_count"] == 1
    assert build_report(manifest, extra_claims=outcome.claims).unkeyed_claim_count == 0


# --- 3: no ambiguity or unmatched count on discarded claims ---------------------


def test_discarded_claims_publish_null_for_the_migration_counts(tmp_path: Path) -> None:
    _stored(tmp_path, [_raw("bbbbbbbbbbbbbbbb")], sha="a" * 64)
    outcome = resolve_ntrs_claims(tmp_path, {"csv_sha256": "b" * 64, "cards": [_row("bbbbbbbbbbbbbbbb", "B")]})
    assert outcome.applied is False
    fields = outcome.summary_fields()
    assert fields["ntrs_migration_ambiguous_claim_count"] is None
    assert fields["ntrs_migration_unmatched_claim_count"] is None


def test_applied_claims_publish_integers_for_the_migration_counts() -> None:
    fields = NtrsOutcome([], True, "a" * 64, None, 2, 3).summary_fields()
    assert fields["ntrs_migration_ambiguous_claim_count"] == 2
    assert fields["ntrs_migration_unmatched_claim_count"] == 3


def test_the_doc_says_null_means_not_applicable() -> None:
    assert "`null` means not applicable" in _DOC
    assert "`ntrs_migration_unmatched_claim_count`" in _DOC


# --- 2: joins bound to one manifest revision -------------------------------------


def test_a_mismatched_revision_joins_nothing_in_either_consumer(tmp_path: Path) -> None:
    _stored(tmp_path, [_raw("aaaaaaaaaaaaaaaa", row_key="aaaaaaaaaaaaaaaa#0")], sha="a" * 64)
    manifest = {"csv_sha256": "b" * 64, "cards": [_row("aaaaaaaaaaaaaaaa", "A")]}
    outcome = resolve_ntrs_claims(tmp_path, manifest)
    assert outcome.claims == [] and outcome.notice is not None
    assert build_report(manifest, extra_claims=outcome.claims).ntrs_claims_applied_row_count == 0


def test_the_report_publishes_the_csv_sha256_of_its_manifest() -> None:
    manifest = {"csv_sha256": "c" * 64, "cards": [_row("aaaaaaaaaaaaaaaa", "A")]}
    assert build_report(manifest).to_dict()["csv_sha256"] == "c" * 64


def test_the_committed_artifacts_share_one_csv_sha256() -> None:
    shas = {}
    for name in ("tier0-manifest-claims", "identifier-claims", "ntrs-claims", "era-buckets"):
        shas[name] = json.loads((_REPO / "data" / "provenance" / f"{name}.json").read_text())["csv_sha256"]
    manifest = json.loads((_REPO / "data" / "manifests" / "latest.json").read_text())["csv_sha256"]
    assert set(shas.values()) == {manifest}, shas


# --- 4: ntrs_claims_applied_row_count counts NTRS claims only -------------------


def test_applied_row_count_ignores_non_ntrs_extra_claims() -> None:
    manifest = {"cards": [_row("aaaaaaaaaaaaaaaa", "A0"), _row("aaaaaaaaaaaaaaaa", "A1")]}
    ntrs = _claim("aaaaaaaaaaaaaaaa", "aaaaaaaaaaaaaaaa#0")
    other = _claim("aaaaaaaaaaaaaaaa", "aaaaaaaaaaaaaaaa#1", ResolutionSource.CATALOGUE)
    assert build_report(manifest, extra_claims=[ntrs, other]).ntrs_claims_applied_row_count == 1


# --- 5 and 6: one search per file; a row without a card_id ----------------------


def test_sibling_rows_of_one_file_search_once_and_are_labelled() -> None:
    manifest = {"cards": [card(title="Apollo 12 Medical Debriefing"), card(title="Apollo 12 Medical Debriefing")]}
    net = Net(Resp(200, _EARLY))
    searches = run_searches(manifest, net.fetcher(), TODAY)
    assert len(net.urls) == 1
    assert [s.row_key for s in searches] == ["a0a0a0a0a0a0a012#0", "a0a0a0a0a0a0a012#1"]
    assert "search_shared_from" not in searches[0].to_dict()
    assert searches[1].to_dict()["search_shared_from"] == "a0a0a0a0a0a0a012#0"


def test_distinct_files_each_search() -> None:
    manifest = {"cards": [card(), card(card_id="a0a0a0a0a0a0a013")]}
    net = Net(Resp(200, _EARLY))
    run_searches(manifest, net.fetcher(), TODAY)
    assert len(net.urls) == 2


def test_a_row_without_a_card_id_is_searched_and_its_claim_joins_only_that_row() -> None:
    cards = [card(card_id=""), card(card_id=""), card()]
    manifest = {"cards": cards}
    net = Net(Resp(200, _EARLY))
    searches = run_searches(manifest, net.fetcher(), TODAY)
    assert [s.row_key for s in searches] == ["no-card-id-0#0", "no-card-id-1#0", "a0a0a0a0a0a0a012#0"]
    assert len(net.urls) == 3
    first = searches[0].claim
    assert first is not None and first.row_key == "no-card-id-0#0" and first.card_id == "no-card-id-0"
    stored = load_ntrs_claims({"csv_sha256": "s", "claims": [first.to_dict()]}, cards)
    assert [c.row_key for c in stored.claims] == ["no-card-id-0#0"]
    report = build_report(manifest, extra_claims=stored.claims)
    assert report.ntrs_claims_applied_row_count == 1
    assert report.unkeyed_claim_count == 0
    assert [o.resolved_by for o in report.outcomes][:2] == ["claim", "unresolved"]


# --- 7: unkeyed and ambiguous are disjoint --------------------------------------


def test_one_claim_never_counts_as_both_unkeyed_and_ambiguous() -> None:
    cards = [
        _row("aaaaaaaaaaaaaaaa", "A0", asset_filename="x.pdf"),
        _row("aaaaaaaaaaaaaaaa", "A1", asset_filename="y.pdf"),
    ]
    data = {"csv_sha256": "s", "claims": [_raw("aaaaaaaaaaaaaaaa"), _raw("bbbbbbbbbbbbbbbb")]}
    loaded = load_ntrs_claims(data, cards)
    assert loaded.migration_ambiguous == 1 and loaded.migration_unmatched == 1
    report = build_report({"cards": cards}, extra_claims=loaded.claims)
    assert report.unkeyed_claim_count == 0
    total = len(data["claims"])
    assert loaded.migration_ambiguous + loaded.migration_unmatched + report.unkeyed_claim_count + len(loaded.claims) == total


def test_a_keyless_claim_in_a_keyed_file_is_unkeyed_only() -> None:
    cards = [_row("aaaaaaaaaaaaaaaa", "A")]
    data = {"csv_sha256": "s", "claims": [_raw("aaaaaaaaaaaaaaaa", row_key="aaaaaaaaaaaaaaaa#0"), _raw("aaaaaaaaaaaaaaaa", row_key="")]}
    loaded = load_ntrs_claims(data, cards)
    assert loaded.migration_ambiguous == 0 and loaded.migration_unmatched == 0
    assert build_report({"cards": cards}, extra_claims=loaded.claims).unkeyed_claim_count == 1


def test_the_doc_defines_unkeyed_and_ambiguous_as_disjoint() -> None:
    assert "disjoint" in _DOC


# --- 8: classify(report=...) ------------------------------------------------------


def test_classify_refuses_a_report_built_from_another_revision_of_equal_length() -> None:
    rows = [_row("aaaaaaaaaaaaaaaa", "A0"), _row("bbbbbbbbbbbbbbbb", "B0")]
    mine = {"csv_sha256": "a" * 64, "cards": rows}
    theirs = {"csv_sha256": "b" * 64, "cards": rows}
    report = build_report(theirs)
    with pytest.raises(ValueError, match="csv_sha256"):
        classify(rows[0], row_key="aaaaaaaaaaaaaaaa#0", manifest=mine, report=report)
    assert classify(rows[0], row_key="aaaaaaaaaaaaaaaa#0", manifest=theirs, report=report).row_key == "aaaaaaaaaaaaaaaa#0"


def test_classify_refuses_a_report_without_the_manifest_it_was_built_from() -> None:
    rows = [_row("aaaaaaaaaaaaaaaa", "A0")]
    report = build_report({"cards": rows})
    with pytest.raises(ValueError, match="manifest"):
        classify(rows[0], row_key="aaaaaaaaaaaaaaaa#0", report=report)


def test_classify_documents_why_the_single_card_path_cannot_compare_the_card() -> None:
    doc = classify.__doc__ or ""
    assert "no manifest row to compare the card with" in " ".join(doc.split())
