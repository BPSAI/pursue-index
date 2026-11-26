"""A row's route is decided once; the era summary and the coverage report agree on it.

A claim resolves a row even when its file's dated rows conflict; a conflicted row
with no claim stays unresolved and is triaged with the conflict reason.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import Era
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import RESOLVED_BY_CLAIM, UNRESOLVED, build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim


@pytest.mark.parametrize(
    ("has_claim", "era", "conflicted", "expected"),
    [
        (True, Era.MODERN_OPERATIONAL, False, "CLAIM"),
        (True, Era.MODERN_OPERATIONAL, True, "CLAIM"),
        (True, Era.UNDATED, True, "CLAIM"),
        (False, Era.MODERN_OPERATIONAL, True, "UNRESOLVED"),
        (False, Era.MODERN_OPERATIONAL, False, "ERA"),
        (False, Era.UNDATED, False, "UNRESOLVED"),
    ],
)
def test_row_route_precedence(has_claim: bool, era: Era, conflicted: bool, expected: str) -> None:
    from pursue_index.file_basis import Route, row_route

    assert row_route(has_claim, era, conflicted) is Route[expected]


def _row(title: str, date_: str) -> dict[str, Any]:
    return {"card_id": "aaaa", "title": title, "agency": "DOW", "release_date": "5/8/2026", "incident_date": date_}


def _claim(row_key: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id="aaaa",
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def test_summary_and_report_agree_on_a_conflicting_file_with_a_claimed_row() -> None:
    manifest = {"cards": [_row("D1", "2022-05-06"), _row("D2", "2019-03-04"), _row("D3", "2021-01-01")]}
    claims = [_claim("aaaa#0")]
    out = build_output(manifest, bucket(manifest, extra_claims=claims))
    report = build_report(manifest, extra_claims=claims)

    by_key = {o.row_key: o.resolved_by for o in report.outcomes}
    assert by_key == {"aaaa#0": RESOLVED_BY_CLAIM, "aaaa#1": UNRESOLVED, "aaaa#2": UNRESOLVED}

    assert [e["row_key"] for e in out["superseded_by_claim"]] == ["aaaa#0"]
    assert out["no_prior_release_rows"] == []
    triaged = {e["row_key"]: e for e in out["undated_triage"]}
    assert set(triaged) == {"aaaa#1", "aaaa#2"}
    assert all("conflicting document dates" in e["reason"] for e in triaged.values())
