"""Every manifest row sits in exactly one per-row array of ``era-buckets.json``.

``claim_resolved_rows`` holds the rows a claim (own or inherited) resolves that
``superseded_by_claim`` does not already list: a claimed row that is not modern, an
undated one for example. The one remaining row set with no record is a dated row
that routes ``unresolved`` with no conflict: a pre-2015 document with no claim, which
is neither a negative nor a triage entry.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pursue_index.catalogue_load import load_catalogue
from pursue_index.claim_precedence import POSITIVE_TIER_PRECEDENCE
from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import Era
from pursue_index.file_basis import assess
from pursue_index.era_bucketing import classify_reconciled
from pursue_index.ntrs_claims_load import resolve_ntrs_claims
from pursue_index.paths import repo_root
from pursue_index.provenance import DateBasis
from pursue_index.provenance_report import build_report, classify
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim

_ARRAYS = ("no_prior_release_rows", "superseded_by_claim", "claim_resolved_rows", "undated_triage")


def _row(title: str, date_: str | None = None, card_id: str = "aaaa") -> dict[str, Any]:
    card = {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026"}
    if date_:
        card["incident_date"] = date_
    return card


def _claim(row_key: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=row_key.split("#")[0],
        row_key=row_key,
        tier=POSITIVE_TIER_PRECEDENCE[0],
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


_MANIFEST = {
    "cards": [
        _row("own-undated"),  # aaaa#0 claim, undated -> claim_resolved_rows
        _row("sib-modern", "2022-05-06"),  # aaaa#1 inherited, modern -> superseded
        _row("sib-old", "1975"),  # aaaa#2 inherited, pre-2015 -> claim_resolved_rows
        _row("plain-modern", "2022-05-06", "bbbb"),  # era -> negative
        _row("lone-undated", None, "cccc"),  # triage
        _row("lone-old", "1975", "dddd"),  # unresolved, dated, no conflict: no record
        _row("conf-a", "2022-05-06", "eeee"),  # conflict file, unclaimed -> triage
        _row("conf-b", "1975", "eeee"),
    ]
}
_CLAIMS = [_claim("aaaa#0")]


def _no_record(rows: list[Any]) -> set[str]:
    return {
        r.era.row_key
        for r in rows
        if r.route.value == "unresolved" and r.conflict is None and r.era.era is not Era.UNDATED
    }


def _check(out: dict[str, Any], rows: list[Any]) -> None:
    placed: dict[str, list[str]] = {}
    for name in _ARRAYS:
        for record in out[name]:
            placed.setdefault(record["row_key"], []).append(name)
    assert all(len(where) == 1 for where in placed.values()), placed
    expected = {r.era.row_key for r in rows}
    assert set(placed) | _no_record(rows) == expected
    assert not set(placed) & _no_record(rows)
    assert out["claim_resolved_row_count"] == len(out["claim_resolved_rows"])


def test_a_claim_resolved_row_that_is_not_modern_is_listed() -> None:
    out = build_output(_MANIFEST, bucket(_MANIFEST, extra_claims=_CLAIMS))
    assert [r["row_key"] for r in out["claim_resolved_rows"]] == ["aaaa#0", "aaaa#2"]
    assert out["claim_resolved_row_count"] == 2
    record = {r["row_key"]: r for r in out["claim_resolved_rows"]}
    assert record["aaaa#2"]["claim_inherited_from"] == "aaaa#0"
    assert "claim_inherited_from" not in record["aaaa#0"]
    assert [r["row_key"] for r in out["superseded_by_claim"]] == ["aaaa#1"]


def test_every_row_is_in_exactly_one_array_on_fixtures() -> None:
    cards = _MANIFEST["cards"]
    rows = assess(cards, classify_reconciled(cards), (), _CLAIMS)
    out = build_output(_MANIFEST, bucket(_MANIFEST, extra_claims=_CLAIMS))
    _check(out, rows)
    assert _no_record(rows) == {"dddd#0"}
    no_claims = build_output(_MANIFEST, bucket(_MANIFEST))
    _check(no_claims, assess(cards, classify_reconciled(cards), (), []))
    assert no_claims["claim_resolved_rows"] == []


def test_every_row_is_in_exactly_one_array_on_the_real_data() -> None:
    root = repo_root()
    manifest = json.loads((root / "data" / "manifests" / "latest.json").read_text())
    claims = list(resolve_ntrs_claims(root, manifest).claims)
    cards = manifest["cards"]
    rows = assess(cards, classify_reconciled(cards), load_catalogue(root).entries, claims)
    stored = json.loads((root / "data" / "provenance" / "era-buckets.json").read_text())
    _check(stored, rows)
    assert stored["claim_resolved_row_count"] >= 19


def test_classify_agrees_with_build_report_for_every_row_of_a_multi_row_file() -> None:
    report = build_report(_MANIFEST, extra_claims=_CLAIMS)
    for outcome, card in zip(report.outcomes, _MANIFEST["cards"], strict=True):
        got = classify(card, external=_CLAIMS, row_key=outcome.row_key, manifest=_MANIFEST)
        assert got == outcome, outcome.row_key
    assert {o.resolved_by for o in report.outcomes} >= {"claim", "claim_inherited", "era", "unresolved"}
