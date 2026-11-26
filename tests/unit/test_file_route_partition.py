"""The file route is the mixed-outcome partition; both stages share one ``row_route``.

claim: any row has a claim. era: no claim and every row routes era. unresolved:
otherwise. The file counts partition ``file_count`` and the row counts partition
``card_row_count``. Fixtures only.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import pursue_index.file_basis as file_basis
from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import Era
from pursue_index.file_basis import Route, file_route
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim

_REPO = Path(__file__).resolve().parents[2]


def _row(card_id: str, title: str, **dates: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **dates}


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


# --- the file route over row routes ------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([Route.CLAIM], Route.CLAIM),
        ([Route.CLAIM, Route.UNRESOLVED], Route.CLAIM),
        ([Route.UNRESOLVED, Route.ERA, Route.CLAIM], Route.CLAIM),
        ([Route.ERA, Route.ERA], Route.ERA),
        ([Route.ERA, Route.UNRESOLVED], Route.UNRESOLVED),
        ([Route.UNRESOLVED, Route.UNRESOLVED], Route.UNRESOLVED),
    ],
)
def test_file_route_table(rows: list[Route], expected: Route) -> None:
    assert file_route(rows) is expected


# --- one row_route, used by both modules --------------------------------------------


@pytest.mark.parametrize(
    ("has_claim", "era", "conflicted", "expected"),
    [
        (True, Era.MODERN_OPERATIONAL, False, Route.CLAIM),
        (True, Era.UNDATED, False, Route.CLAIM),
        (True, Era.MODERN_OPERATIONAL, True, Route.CLAIM),
        (False, Era.MODERN_OPERATIONAL, False, Route.ERA),
        (False, Era.MODERN_OPERATIONAL, True, Route.UNRESOLVED),
        (False, Era.PRE_1970, False, Route.UNRESOLVED),
        (False, Era.UNDATED, False, Route.UNRESOLVED),
    ],
)
def test_row_route_table(has_claim: bool, era: Era, conflicted: bool, expected: Route) -> None:
    assert file_basis.row_route(has_claim, era, conflicted) is expected


def test_the_bucketing_and_the_report_both_go_through_the_one_row_route(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {"cards": [_row("aaaa", "A1", incident_date="2022-05-06")]}
    assert bucket(manifest).claims and build_report(manifest).resolved_by_era == 1
    monkeypatch.setattr(file_basis, "row_route", lambda *_a, **_k: Route.UNRESOLVED)
    assert bucket(manifest).claims == []
    report = build_report(manifest)
    assert (report.resolved_by_era, report.unresolved, report.row_counts["era"]) == (0, 1, 0)


# --- the partition over fixtures -----------------------------------------------------


def _fixture() -> dict[str, Any]:
    return {
        "cards": [
            _row("claimed", "C1", incident_date="2022-05-06"),  # any-row claim, other row unclaimed
            _row("claimed", "C2", incident_date="2022-05-06"),
            _row("modern", "M1", incident_date="2022-05-06"),  # all era (one reconciled)
            _row("modern", "M2"),
            _row("old", "O1", incident_date="1952-07-01"),  # unresolved, no era row
            _row("conf", "F1", incident_date="2022-05-06"),  # conflict, no claim: unresolved
            _row("conf", "F2", incident_date="1975"),
            _row("lone", "L1"),  # undated
        ]
    }


def _both(claims: list[ResolvedClaim]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _fixture()
    return build_output(manifest, bucket(manifest, extra_claims=claims)), build_report(manifest, extra_claims=claims).to_dict()


def test_any_row_claim_routes_the_whole_file_to_claim_and_the_partitions_add_up() -> None:
    out, report = _both([_claim("claimed", "claimed#1")])
    assert out["file_route_counts"] == {"claim": 1, "era": 1, "unresolved": 3}
    assert out["row_route_counts"] == {"claim": 1, "claim_inherited": 1, "era": 2, "unresolved": 4}
    assert sum(out["file_route_counts"].values()) == out["file_count"] == 5
    assert sum(out["row_route_counts"].values()) == out["card_row_count"] == 8
    # the unclaimed row of the claimed file inherits the file's claim, so it emits no negative
    assert (report["resolved_by_claim"], report["resolved_by_era"], report["unresolved"]) == (1, 1, 3)
    assert report["row_counts"] == out["row_route_counts"]
    assert report["unresolved_files"] == ["old", "conf", "lone"]


def test_a_file_with_every_row_on_era_is_era_even_when_one_row_was_reconciled() -> None:
    out, _ = _both([])
    assert out["file_route_counts"]["era"] == 2  # "claimed" (no claim here) and "modern"
    assert out["file_route_counts"]["claim"] == 0


def test_a_file_with_some_era_rows_and_some_unresolved_is_partially_resolved() -> None:
    both = ["aaaa", "aaaa"]
    assert file_basis.partially_resolved_files([Route.ERA, Route.UNRESOLVED], both) == ["aaaa"]
    assert file_basis.partially_resolved_files([Route.ERA, Route.UNRESOLVED], ["aaaa", "bbbb"]) == []
    assert file_basis.partially_resolved_files([Route.UNRESOLVED, Route.UNRESOLVED], both) == []
    assert file_basis.partially_resolved_files([Route.ERA, Route.ERA], both) == []
    # a claim anywhere makes the file a claim file, so it is not "unresolved"
    assert file_basis.partially_resolved_files([Route.CLAIM, Route.ERA, Route.UNRESOLVED], ["a", "a", "a"]) == []


def test_partially_resolved_count_equals_its_list_in_both_outputs() -> None:
    out, report = _both([])
    assert out["partially_resolved_file_count"] == len(out["partially_resolved_files"]) == 0
    assert report["partially_resolved_file_count"] == len(report["partially_resolved_files"]) == 0


# --- no `mixed` ----------------------------------------------------------------------


def test_mixed_is_absent_from_both_era_maps_and_the_report() -> None:
    out, report = _both([])
    assert "mixed" not in out["era_file_counts"] and "mixed" not in out["era_row_counts"]
    assert set(out["era_file_counts"]) == set(out["era_row_counts"]) == {e.value for e in Era}
    assert "mixed" not in report["unresolved_by_era"]


def test_the_stored_artifact_has_no_mixed_bucket() -> None:
    stored = json.loads((_REPO / "data" / "provenance" / "era-buckets.json").read_text())
    assert "mixed" not in stored["era_file_counts"] and "mixed" not in stored["era_row_counts"]


# --- agreement and the conflict fail-safe -----------------------------------------------


def test_bucketing_and_report_agree_on_every_row_route() -> None:
    claims = [_claim("claimed", "claimed#1"), _claim("conf", "conf#1")]
    manifest = _fixture()
    out = build_output(manifest, bucket(manifest, extra_claims=claims))
    report = build_report(manifest, extra_claims=claims)
    assert out["row_route_counts"] == report.row_counts
    assert out["file_route_counts"] == {
        "claim": report.resolved_by_claim,
        "era": report.resolved_by_era,
        "unresolved": report.unresolved,
    }
    assert out["partially_resolved_files"] == list(report.partially_resolved_files)


def test_a_conflict_file_with_a_claimed_row_is_a_claim_file_and_its_other_rows_inherit() -> None:
    claims = [_claim("conf", "conf#1")]
    out, report = _both(claims)
    assert out["file_route_counts"]["claim"] == 1 and "conf" not in report["unresolved_files"]
    assert (out["row_route_counts"]["claim"], out["row_route_counts"]["claim_inherited"]) == (1, 1)
    assert [e["row_key"] for e in out["undated_triage"] if e["card_id"] == "conf"] == []
    assert report["tier_file_counts"] == {ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED.value: 1}


def test_a_conflict_file_with_no_claim_is_unresolved_undated_and_listed_with_its_reason() -> None:
    out, report = _both([])
    assert "conf" in report["unresolved_files"]
    assert report["unresolved_by_era"]["undated"] == 2  # "conf" and "lone"
    reasons = [e["reason"] for e in out["undated_triage"] if e["card_id"] == "conf"]
    assert len(reasons) == 2 and all("conf#0=2015_plus/2022, conf#1=1970_1989/1975" in r for r in reasons)


def test_the_real_corpus_partitions_add_up() -> None:
    stored = json.loads((_REPO / "data" / "provenance" / "era-buckets.json").read_text())
    assert sum(stored["file_route_counts"].values()) == stored["file_count"]
    assert sum(stored["row_route_counts"].values()) == stored["card_row_count"]
    assert stored["partially_resolved_file_count"] == len(stored["partially_resolved_files"])
