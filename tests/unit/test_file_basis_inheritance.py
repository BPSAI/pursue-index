"""Headline counts are per source file; an unkeyed claim matches nothing; a
reconciled row takes its dated sibling's prior-release status.

Fixtures only; nothing here reads the stored artifacts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pursue_index.claim_precedence import positive_claims
from pursue_index.era_bucketing import bucket, build_output
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


def _row(card_id: str, title: str, **dates: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **dates}


def _dated(card_id: str = "aaaa", title: str = "D1", date_: str = "2022-05-06") -> dict[str, Any]:
    return _row(card_id, title, incident_date=date_)


def _claim(card_id: str, row_key: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=card_id,
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


# --- item 1: count per file ---------------------------------------------------


def test_a_three_row_file_counts_once_in_its_era_and_once_as_no_prior_release() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1"), _row("aaaa", "PR2")]}
    result = bucket(manifest)
    out = build_output(manifest, result)
    assert out["era_file_counts"]["2015_plus"] == 1
    assert out["no_prior_release_file_count"] == 1
    assert out["era_row_counts"]["2015_plus"] == 3
    assert out["no_prior_release_row_count"] == 3
    assert out["file_count"] == 1


def test_a_conflicting_file_counts_once_under_undated() -> None:
    cards = [_dated(date_="2022-05-06"), _dated(title="D2", date_="1975"), _row("aaaa", "PR1")]
    out = build_output({"cards": cards}, bucket({"cards": cards}))
    assert out["era_file_counts"]["undated"] == 1
    assert sum(out["era_file_counts"].values()) == out["file_count"] == 1
    # Rows keep their own era; only the file is undated.
    assert (out["era_row_counts"]["undated"], out["era_row_counts"]["2015_plus"]) == (1, 1)
    assert out["era_row_counts"]["1970_1989"] == 1


def test_the_coverage_report_counts_per_file_too() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1"), _row("aaaa", "PR2")]}
    report = build_report(manifest)
    assert report.resolved_by_era == 1
    assert report.file_count == 1
    assert report.row_counts["era"] == 3


# --- item 2: an unkeyed claim matches nothing --------------------------------


def test_an_empty_row_key_resolves_neither_row_and_is_counted() -> None:
    manifest = {"cards": [_dated(), _dated(title="D2")]}
    report = build_report(manifest, extra_claims=[_claim("aaaa", "")])
    assert report.resolved_by_claim == 0
    assert report.row_counts["claim"] == 0
    assert report.claims_without_row_key == 1
    result = bucket(manifest, extra_claims=[_claim("aaaa", "")])
    assert result.superseded == []
    assert result.claims_without_row_key == 1
    assert build_output(manifest, result)["claims_without_row_key"] == 1


def test_a_keyed_claim_resolves_exactly_its_row() -> None:
    cards = [_dated(), _dated(title="D2")]
    keyed = [_claim("aaaa", "aaaa#1")]
    assert positive_claims(cards[0], external=keyed, row_key="aaaa#0") == []
    assert len(positive_claims(cards[1], external=keyed, row_key="aaaa#1")) == 1
    result = bucket({"cards": cards}, extra_claims=keyed)
    assert [s["row_key"] for s in result.superseded] == ["aaaa#1"]
    assert getattr(result, "claims_without_row_key", None) == 0


# --- item 3: a reconciled row inherits its sibling's status -----------------


def test_a_reconciled_row_inherits_its_siblings_positive_claim() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1")]}
    result = bucket(manifest, extra_claims=[_claim("aaaa", "aaaa#0")])
    assert result.claims == []
    assert sorted(s["row_key"] for s in result.superseded) == ["aaaa#0", "aaaa#1"]
    inherited = {s["row_key"]: s for s in result.superseded}["aaaa#1"]
    assert inherited["era_reconciled_from"] == "aaaa#0"
    assert inherited["superseding_tier"] == ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED.value
    report = build_report(manifest, extra_claims=[_claim("aaaa", "aaaa#0")])
    assert [o.resolved_by for o in report.outcomes] == ["claim", "claim"]


def test_a_reconciled_record_is_labelled_and_names_its_sibling() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1")]}
    records = {r["row_key"]: r for r in build_output(manifest, bucket(manifest))["no_prior_release_rows"]}
    assert records["aaaa#1"].get("reconciled") is True
    assert records["aaaa#1"]["era_reconciled_from"] == "aaaa#0"
    assert "aaaa#0" in records["aaaa#1"]["rationale"]
    assert "reconciled" not in records["aaaa#0"]


# --- inheritance is file-level: any row's claim covers every row of its file --


def _undated(title: str = "U1") -> dict[str, Any]:
    return _row("aaaa", title)


def test_an_undated_claimed_row_covers_its_dated_unclaimed_sibling() -> None:
    manifest = {"cards": [_undated(), _dated()]}
    claims = [_claim("aaaa", "aaaa#0")]
    result = bucket(manifest, extra_claims=claims)
    out = build_output(manifest, result)
    assert out["no_prior_release_rows"] == []
    assert result.claims == []
    by_key = {s["row_key"]: s for s in result.superseded}
    assert sorted(by_key) == ["aaaa#0", "aaaa#1"]
    assert by_key["aaaa#1"]["claim_inherited_from"] == "aaaa#0"
    assert "claim_inherited_from" not in by_key["aaaa#0"]
    assert out["file_route_counts"]["claim"] == 1
    report = build_report(manifest, extra_claims=claims)
    assert [o.resolved_by for o in report.outcomes] == ["claim", "claim"]
    assert report.file_route_counts["claim"] == 1


def test_a_dated_claimed_row_still_covers_its_reconciled_sibling() -> None:
    manifest = {"cards": [_dated(), _undated()]}
    result = bucket(manifest, extra_claims=[_claim("aaaa", "aaaa#0")])
    assert result.claims == []
    by_key = {s["row_key"]: s for s in result.superseded}
    assert by_key["aaaa#1"]["era_reconciled_from"] == "aaaa#0"
    assert by_key["aaaa#1"]["claim_inherited_from"] == "aaaa#0"


def test_a_conflicting_file_with_one_claimed_row_emits_no_negative() -> None:
    cards = [_dated(date_="2022-05-06"), _dated(title="D2", date_="2019-03-04"), _undated()]
    result = bucket({"cards": cards}, extra_claims=[_claim("aaaa", "aaaa#2")])
    assert result.claims == []
    by_key = {s["row_key"]: s for s in result.superseded}
    assert sorted(by_key) == ["aaaa#0", "aaaa#1"]
    assert {e["claim_inherited_from"] for e in by_key.values()} == {"aaaa#2"}
    assert build_output({"cards": cards}, result)["no_prior_release_rows"] == []


def test_the_strongest_claim_in_the_file_is_inherited_ties_by_lowest_row_key() -> None:
    cards = [_undated("U0"), _dated(title="D1"), _dated(title="D2", date_="2023-01-01")]
    claims = [_claim("aaaa", "aaaa#2"), _claim("aaaa", "aaaa#0")]
    result = bucket({"cards": cards}, extra_claims=claims)
    by_key = {s["row_key"]: s for s in result.superseded}
    assert by_key["aaaa#1"]["claim_inherited_from"] == "aaaa#0"
    assert "claim_inherited_from" not in by_key["aaaa#2"]


def test_a_file_with_no_claim_is_unchanged() -> None:
    manifest = {"cards": [_undated(), _dated()]}
    result = bucket(manifest)
    assert result.superseded == []
    assert [c.row_key for c in result.claims] == ["aaaa#0", "aaaa#1"]
