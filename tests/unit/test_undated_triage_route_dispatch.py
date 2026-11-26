"""``undated_triage`` lists only rows whose route is ``unresolved``.

Identity (see the schema doc, *The row route*): every undated row routes ``claim``
or ``unresolved`` (never ``era``), and a conflicted dated row that no claim resolves
is also triaged, so
``undated_triage_row_count + undated claim-routed rows
== era_row_counts["undated"] + conflicted dated unresolved rows``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.era_bucketing import bucket, build_output, classify_reconciled
from pursue_index.era_models import Era
from pursue_index.file_basis import Route, assess
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


def _check(manifest: dict[str, Any], claims: list[ResolvedClaim]) -> tuple[int, int]:
    """Assert the invariant; return (triage rows, undated claim-routed rows)."""
    result = bucket(manifest, extra_claims=claims)
    out = build_output(manifest, result)
    cards = manifest["cards"]
    rows = assess(cards, classify_reconciled(cards), (), claims)
    unresolved = {r.era.row_key for r in rows if r.route is Route.UNRESOLVED}
    claimed = {r.era.row_key for r in rows if r.route is Route.CLAIM}
    triaged = {t["row_key"] for t in out["undated_triage"]}
    assert triaged <= unresolved
    assert not triaged & claimed
    undated_claim = sum(1 for r in rows if r.route is Route.CLAIM and r.era.era is Era.UNDATED)
    dated_conflicted = sum(
        1 for r in rows if r.route is Route.UNRESOLVED and r.conflict and r.era.era is not Era.UNDATED
    )
    assert out["undated_triage_row_count"] + undated_claim == out["era_row_counts"]["undated"] + dated_conflicted
    return out["undated_triage_row_count"], undated_claim


def test_an_undated_row_with_a_claim_is_not_triaged_and_is_claim_routed() -> None:
    manifest = {"cards": [_row("aaaa", "U1")]}
    key = bucket(manifest).cards[0].row_key
    claims = [_claim("aaaa", key)]
    out = build_output(manifest, bucket(manifest, extra_claims=claims))
    assert out["undated_triage"] == []
    assert out["undated_triage_row_count"] == 0
    assert out["row_route_counts"]["claim"] == 1
    assert out["superseded_by_claim"] == [] and out["no_prior_release_rows"] == []
    report = build_report(manifest, extra_claims=claims)
    assert report.resolved_by_claim == 1
    assert report.row_counts["claim"] == 1


def test_invariant_over_a_mixed_fixture() -> None:
    cards = [
        _row("aaaa", "U-claimed"),
        _row("bbbb", "U-plain"),
        _row("cccc", "D", incident_date="2022-05-06"),
        _row("dddd", "C1", incident_date="2022-05-06"),
        _row("dddd", "C2", incident_date="1975"),
        _row("eeee", "Old", incident_date="1975"),
    ]
    keys = {c.title: c.row_key for c in bucket({"cards": cards}).cards}
    triage, undated_claim = _check({"cards": cards}, [_claim("aaaa", keys["U-claimed"])])
    assert undated_claim == 1
    assert triage >= 1


def test_invariant_over_the_real_corpus() -> None:
    from pursue_index.catalogue_load import load_catalogue
    from pursue_index.ntrs_claims_load import resolve_ntrs_claims
    from pursue_index.paths import repo_root as _resolve_repo_root

    root = _resolve_repo_root()
    manifest = json.loads((root / "data" / "manifests" / "latest.json").read_text())
    catalogue = load_catalogue(root)
    claims = list(resolve_ntrs_claims(root, manifest).claims)
    cards = manifest["cards"]
    rows = assess(cards, classify_reconciled(cards), catalogue.entries, claims)
    stored = json.loads((root / "data" / "provenance" / "era-buckets.json").read_text())
    triaged = {t["row_key"] for t in stored["undated_triage"]}
    unresolved = {r.era.row_key for r in rows if r.route is Route.UNRESOLVED}
    claimed = {r.era.row_key for r in rows if r.route is Route.CLAIM}
    assert triaged <= unresolved and not triaged & claimed
    undated_claim = sum(1 for r in rows if r.route is Route.CLAIM and r.era.era is Era.UNDATED)
    dated_conflicted = sum(
        1 for r in rows if r.route is Route.UNRESOLVED and r.conflict and r.era.era is not Era.UNDATED
    )
    assert (
        stored["undated_triage_row_count"] + undated_claim
        == stored["era_row_counts"]["undated"] + dated_conflicted
    )
