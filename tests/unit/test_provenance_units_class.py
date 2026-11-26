"""Unit naming and symmetry of the provenance schema; the shared key set; inherited conflicts.

Fixtures only.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pursue_index import file_counts
from pursue_index.claim_precedence import POSITIVE_TIER_PRECEDENCE
from pursue_index.era_bucketing import bucket, build_output, classify_rows
from pursue_index.file_basis import _strongest
from pursue_index.file_counts import tallies
from pursue_index.ntrs_claims_load import NtrsOutcome
from pursue_index.provenance import DateBasis
from pursue_index.provenance_report import build_report, classify
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim

_DOC = (Path(__file__).resolve().parents[2] / "docs" / "provenance-artifacts-schema.md").read_text()


def _row(card_id: str, title: str, agency: str = "DOW", date_: str | None = None) -> dict[str, Any]:
    card = {"card_id": card_id, "title": title, "agency": agency, "release_date": "5/8/2026"}
    if date_:
        card["incident_date"] = date_
    return card


def _claim(row_key: str, tier_index: int = 0) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=row_key.split("#")[0],
        row_key=row_key,
        tier=POSITIVE_TIER_PRECEDENCE[tier_index],
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


# --- rows 1, 2: the unit is in the name --------------------------------------


def test_the_claim_and_search_tallies_carry_their_unit_in_the_name() -> None:
    manifest = {"cards": [_row("aaaa", "A", date_="2022-05-06")]}
    unkeyed = ResolvedClaim(**{**_claim("aaaa#0").__dict__, "row_key": ""})
    out = build_output(manifest, bucket(manifest, extra_claims=[unkeyed]))
    assert out["unkeyed_claim_count"] == 1 and "claims_without_row_key" not in out
    report = build_report(manifest, extra_claims=[unkeyed])
    assert report.to_dict()["unkeyed_claim_count"] == 1 and "claims_without_row_key" not in report.to_dict()
    summary = NtrsOutcome([], True, "a" * 64, None, 2).summary_fields()
    assert summary["ntrs_migration_ambiguous_claim_count"] == 2
    assert "ntrs_claims_migration_ambiguous_count" not in summary


def test_the_ntrs_search_tally_is_named_for_its_rows() -> None:
    from pursue_index.ntrs_source import build_output as ntrs_output

    out = ntrs_output({"cards": []}, [], {})
    assert out["searched_row_count"] == 0 and "searched_count" not in out


def test_the_doc_states_the_claim_unit_rule() -> None:
    text = " ".join(_DOC.split())
    for term in ("`unkeyed_claim_count`", "`ntrs_migration_ambiguous_claim_count`", "`searched_row_count`", "`_claim_count`"):
        assert term in text, term
    for old in ("claims_without_row_key", "ntrs_claims_migration_ambiguous_count", "`searched_count` (searches"):
        assert old not in text or "deprecated" in text, old


# --- row 3: agency per file ---------------------------------------------------


def test_agency_file_counts_count_a_file_once() -> None:
    manifest = {"cards": [_row("aaaa", "A1", "CIA"), _row("aaaa", "A2", "CIA"), _row("bbbb", "B", "FBI"), _row("", "N", "FBI")]}
    out = build_output(manifest, bucket(manifest))
    assert out["agency_row_counts"] == {"CIA": 2, "FBI": 2}
    assert out["agency_file_counts"] == {"CIA": 1, "FBI": 2}
    assert sum(out["agency_file_counts"].values()) == out["file_count"]


def test_a_file_whose_rows_disagree_on_agency_counts_once_under_mixed() -> None:
    manifest = {"cards": [_row("aaaa", "A1", "CIA"), _row("aaaa", "A2", "FBI"), _row("bbbb", "B", "FBI")]}
    out = build_output(manifest, bucket(manifest))
    assert out["agency_row_counts"] == {"CIA": 1, "FBI": 2}
    assert out["agency_file_counts"] == {"FBI": 1, "mixed": 1}
    assert sum(out["agency_file_counts"].values()) == out["file_count"] == 2


def test_the_doc_lists_agency_file_counts_with_the_mixed_rule() -> None:
    text = " ".join(_DOC.split())
    assert "`agency_file_counts`" in text and "`mixed`" in text and "agency" in text


# --- row 4: two views of one set ---------------------------------------------


def test_the_file_list_is_the_distinct_file_keys_of_the_row_records_in_order() -> None:
    cards = [_row("bbbb", "B1"), _row("", "N0"), _row("aaaa", "A1"), _row("bbbb", "B2"), _row("aaaa", "A2"), _row("", "N1")]
    manifest = {"cards": cards}
    out = build_output(manifest, bucket(manifest))
    rows = out["no_prior_release_rows"]
    assert len(rows) == 6
    assert out["no_prior_release_files"] == list(dict.fromkeys(r["card_id"] or r["row_key"].split("#")[0] for r in rows))
    assert out["no_prior_release_files"] == ["bbbb", "no-card-id-0", "aaaa", "no-card-id-1"]


def test_the_doc_calls_the_two_no_prior_release_lists_views_of_one_set() -> None:
    assert "two views of one set" in " ".join(_DOC.split())


# --- row 5: the shared key set is enforced by the producer --------------------


def test_the_producer_raises_when_the_two_era_maps_would_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    cards = classify_rows([_row("aaaa", "A", date_="2022-05-06")])
    monkeypatch.setattr(file_counts, "file_eras", lambda *_a, **_k: {"aaaa": "not_an_era"})
    with pytest.raises(ValueError, match="era"):
        tallies(cards, ())
    manifest = {"cards": [_row("aaaa", "A", date_="2022-05-06")]}
    with pytest.raises(ValueError, match="era"):
        bucket(manifest)


def test_every_era_key_is_in_both_maps_zeros_included() -> None:
    manifest = {"cards": [_row("aaaa", "A", date_="2022-05-06")]}
    out = build_output(manifest, bucket(manifest))
    assert set(out["era_file_counts"]) == set(out["era_row_counts"]) and len(out["era_file_counts"]) == 5
    assert 0 in out["era_file_counts"].values()


# --- row 6: an inherited record keeps the date conflict visible ----------------


def test_an_inherited_row_of_a_conflict_file_carries_the_conflict() -> None:
    manifest = {"cards": [_row("aaaa", "D0", date_="2022-05-06"), _row("aaaa", "D1", date_="2019-03-04"), _row("aaaa", "D2", date_="1975")]}
    out = build_output(manifest, bucket(manifest, extra_claims=[_claim("aaaa#1")]))
    superseded = {r["row_key"]: r for r in out["superseded_by_claim"]}
    resolved = {r["row_key"]: r for r in out["claim_resolved_rows"]}
    for record in (superseded["aaaa#0"], resolved["aaaa#2"]):
        assert record["claim_inherited_from"] == "aaaa#1"
        assert record["date_conflict"] is True
        assert "aaaa#0=" in record["date_conflict_reason"] and "aaaa#2=" in record["date_conflict_reason"]
    assert "date_conflict" not in superseded["aaaa#1"]  # its own claim: unchanged
    assert [r["row_key"] for r in out["undated_triage"]] == []  # routing is unchanged


def test_an_inherited_row_of_a_file_without_a_conflict_has_no_conflict_flag() -> None:
    manifest = {"cards": [_row("aaaa", "D0", date_="2022-05-06"), _row("aaaa", "D1", date_="2022-05-06")]}
    out = build_output(manifest, bucket(manifest, extra_claims=[_claim("aaaa#1")]))
    (record,) = out["superseded_by_claim"]
    assert record["claim_inherited_from"] == "aaaa#1" and "date_conflict" not in record


def test_the_doc_documents_the_inherited_conflict_flag() -> None:
    text = " ".join(_DOC.split())
    assert "`date_conflict`" in text and "`date_conflict_reason`" in text


# --- row 7: _strongest is order-independent -----------------------------------


def test_strongest_picks_the_best_tier_then_the_lowest_numeric_index_whatever_the_order() -> None:
    weak, strong = _claim("f#0", 1), _claim("f#0", 0)
    entries = [("f#10", strong), ("f#2", strong), ("f#1", weak)]
    for order in (entries, entries[::-1], [entries[1], entries[2], entries[0]]):
        assert _strongest(list(order)) == ("f#2", strong)
    assert _strongest([]) is None


# --- row 8: classify against a manifest ---------------------------------------


def _manifest() -> dict[str, Any]:
    return {"cards": [_row("aaaa", "A0", date_="2022-05-06"), _row("aaaa", "A1"), _row("bbbb", "B0", date_="1952")]}


def test_classify_accepts_a_prebuilt_report_and_does_not_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, claims = _manifest(), [_claim("aaaa#0")]
    report = build_report(manifest, extra_claims=claims)

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("rebuilt the report")

    monkeypatch.setattr("pursue_index.provenance_report.build_report", boom)
    for outcome in report.outcomes:
        card = manifest["cards"][report.outcomes.index(outcome)]
        assert classify(card, external=claims, row_key=outcome.row_key, manifest=manifest, report=report) == outcome


def test_classify_raises_when_the_card_is_not_the_row_of_its_key() -> None:
    manifest = _manifest()
    with pytest.raises(ValueError, match="aaaa#1"):
        classify(manifest["cards"][0], row_key="aaaa#1", manifest=manifest)
    with pytest.raises(ValueError, match="aaaa#1"):
        classify(manifest["cards"][0], row_key="aaaa#1", manifest=manifest, report=build_report(manifest))
    assert classify(manifest["cards"][1], row_key="aaaa#1", manifest=manifest).row_key == "aaaa#1"
