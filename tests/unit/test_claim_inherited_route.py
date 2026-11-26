"""A row with no claim of its own, in a file where another row has one, routes ``claim_inherited``.

Rows sharing a file are the same document, so a claim on one row is a claim about the
file. Fixtures only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from pursue_index.claim_precedence import POSITIVE_TIER_PRECEDENCE
from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import Era
from pursue_index.provenance import DateBasis
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


def _row(title: str, date_: str | None = None, card_id: str = "aaaa") -> dict[str, Any]:
    card = {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026"}
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


def _routes(manifest: dict[str, Any], claims: list[ResolvedClaim]) -> list[str]:
    return [o.resolved_by for o in build_report(manifest, extra_claims=claims).outcomes]


def test_row_route_puts_an_inherited_claim_above_era_and_below_an_own_claim() -> None:
    from pursue_index.file_basis import Route, row_route

    assert [route.value for route in Route] == ["claim", "claim_inherited", "era", "unresolved"]
    inherited = Route("claim_inherited") if "claim_inherited" in {r.value for r in Route} else None
    assert inherited is not None
    assert row_route(True, Era.MODERN_OPERATIONAL, False, inherited=True) is Route.CLAIM
    assert row_route(False, Era.MODERN_OPERATIONAL, False, inherited=True) is inherited
    assert row_route(False, Era.UNDATED, True, inherited=True) is inherited
    assert row_route(False, Era.MODERN_OPERATIONAL, False, inherited=False) is Route.ERA
    assert row_route(False, Era.MODERN_OPERATIONAL, True, inherited=False) is Route.UNRESOLVED


def test_a_conflict_file_with_one_claimed_row_inherits_to_the_others() -> None:
    manifest = {"cards": [_row("D1", "2022-05-06"), _row("D2", "2019-03-04"), _row("D3", "1975")]}
    claims = [_claim("aaaa#1")]
    result = bucket(manifest, extra_claims=claims)
    out = build_output(manifest, result)
    assert _routes(manifest, claims) == ["claim_inherited", "claim", "claim_inherited"]
    assert out["row_route_counts"] == {"claim": 1, "claim_inherited": 2, "era": 0, "unresolved": 0}
    assert out["file_route_counts"] == {"claim": 1, "era": 0, "unresolved": 0}
    assert out["undated_triage"] == [] and out["no_prior_release_rows"] == []
    report = build_report(manifest, extra_claims=claims).to_dict()
    assert report["row_counts"] == out["row_route_counts"]
    assert report["resolved_by_claim_inherited"] == 2
    assert (report["resolved_by_claim"], report["unresolved"]) == (1, 0)
    # the modern inherited row is published as superseded, labelled with its source
    by_key = {s["row_key"]: s for s in out["superseded_by_claim"]}
    assert by_key["aaaa#0"]["claim_inherited_from"] == "aaaa#1"
    assert "aaaa#2" not in by_key  # 1975 is not modern: nothing to supersede


def test_an_undated_sibling_of_a_claimed_dated_row_is_claim_inherited() -> None:
    manifest = {"cards": [_row("D1", "2022-05-06"), _row("U1")]}
    claims = [_claim("aaaa#0")]
    out = build_output(manifest, bucket(manifest, extra_claims=claims))
    assert _routes(manifest, claims) == ["claim", "claim_inherited"]
    assert out["row_route_counts"]["claim_inherited"] == 1
    assert out["undated_triage"] == []


def test_several_claimed_rows_keep_their_own_and_unclaimed_siblings_take_the_strongest() -> None:
    manifest = {"cards": [_row("U0"), _row("D1", "2022-01-01"), _row("D2", "2022-02-02"), _row("D3", "2022-03-03")]}
    claims = [_claim("aaaa#1", tier_index=1), _claim("aaaa#2", tier_index=0)]
    result = bucket(manifest, extra_claims=claims)
    assert _routes(manifest, claims) == ["claim_inherited", "claim", "claim", "claim_inherited"]
    by_key = {s["row_key"]: s for s in result.superseded}
    assert by_key["aaaa#0"]["claim_inherited_from"] == by_key["aaaa#3"]["claim_inherited_from"] == "aaaa#2"
    assert "claim_inherited_from" not in by_key["aaaa#1"] and "claim_inherited_from" not in by_key["aaaa#2"]
    assert by_key["aaaa#1"]["superseding_tier"] == POSITIVE_TIER_PRECEDENCE[1].value


def test_equally_strong_claims_break_by_lowest_row_key() -> None:
    manifest = {"cards": [_row("D0", "2022-01-01"), _row("D1", "2022-02-02"), _row("D2", "2022-03-03")]}
    claims = [_claim("aaaa#2"), _claim("aaaa#1")]
    by_key = {s["row_key"]: s for s in bucket(manifest, extra_claims=claims).superseded}
    assert by_key["aaaa#0"]["claim_inherited_from"] == "aaaa#1"


@pytest.mark.parametrize("with_claim", [True, False])
def test_both_partitions_sum_with_claim_inherited_included(with_claim: bool) -> None:
    manifest = {
        "cards": [
            _row("D1", "2022-05-06"), _row("U1"),  # aaaa
            _row("F1", "2022-05-06", "bbbb"), _row("F2", "1975", "bbbb"),  # conflict
            _row("M1", "2022-05-06", "cccc"),  # plain era
            _row("L1", None, "dddd"),  # lone undated
        ]
    }
    claims = [_claim("aaaa#0"), _claim("bbbb#1")] if with_claim else []
    out = build_output(manifest, bucket(manifest, extra_claims=claims))
    report = build_report(manifest, extra_claims=claims)
    assert set(out["row_route_counts"]) == {"claim", "claim_inherited", "era", "unresolved"}
    assert set(out["file_route_counts"]) == {"claim", "era", "unresolved"}
    assert sum(out["row_route_counts"].values()) == out["card_row_count"] == 6
    assert sum(out["file_route_counts"].values()) == out["file_count"] == 4
    assert out["row_route_counts"] == report.row_counts
    assert out["row_route_counts"]["claim_inherited"] == (2 if with_claim else 0)
    assert report.resolved_by_claim_inherited == out["row_route_counts"]["claim_inherited"]
