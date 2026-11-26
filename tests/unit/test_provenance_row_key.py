"""Each manifest row carries a stable key: ``<card_id>#<n>``.

``card_id`` is per source file, and several upstream rows can name one file, so
it cannot identify a row. ``n`` is the 0-based position of the row among the
rows sharing its ``card_id``, in manifest order.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.identifier_resolver import resolve_manifest
from pursue_index.provenance_report import build_report
from pursue_index.tier0_sweep import sweep

_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "manifests" / "latest.json"


def _card(card_id: str, title: str) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026"}


def _manifest() -> dict[str, Any]:
    return {
        "cards": [
            _card("aaaa", "first"),
            _card("bbbb", "only"),
            _card("aaaa", "second"),
            _card("aaaa", "third"),
        ]
    }


def test_duplicate_rows_get_distinct_keys_in_manifest_order() -> None:
    keys = [c.row_key for c in bucket(_manifest()).cards]
    assert keys == ["aaaa#0", "bbbb#0", "aaaa#1", "aaaa#2"]


def test_a_unique_card_id_gets_index_zero() -> None:
    (only,) = bucket({"cards": [_card("cccc", "solo")]}).cards
    assert only.row_key == "cccc#0"


def test_keys_are_stable_across_a_rebuild_of_an_unchanged_manifest() -> None:
    manifest = _manifest()
    first = build_output(manifest, bucket(manifest))
    second = build_output(manifest, bucket(manifest))
    assert [c["row_key"] for c in first["cards"]] == [c["row_key"] for c in second["cards"]]
    assert first == second


def test_row_key_follows_card_id_in_the_artifact_entry() -> None:
    (entry,) = build_output({"cards": [_card("cccc", "solo")]}, bucket({"cards": [_card("cccc", "solo")]}))["cards"]
    assert list(entry)[:2] == ["card_id", "row_key"]


def test_every_per_row_list_of_the_era_artifact_carries_the_key() -> None:
    manifest = {"cards": [_card("aaaa", "x"), _card("aaaa", "y")]}
    out = build_output(manifest, bucket(manifest))
    assert [r["row_key"] for r in out["undated_triage"]] == ["aaaa#0", "aaaa#1"]
    modern = {"cards": [{**_card("dddd", "m"), "incident_date": "2022-05-06"}]}
    claim = build_output(modern, bucket(modern))["no_prior_release"][0]
    assert claim["row_key"] == "dddd#0"


def test_the_coverage_report_outcomes_carry_the_key() -> None:
    report = build_report(_manifest())
    assert [o.row_key for o in report.outcomes] == ["aaaa#0", "bbbb#0", "aaaa#1", "aaaa#2"]


def test_the_identifier_resolver_keys_each_claim_by_its_row() -> None:
    crest = "Doc CIA-RDP79B00752A000300070001-6"
    manifest = {"cards": [_card("aaaa", crest), _card("aaaa", crest)]}
    assert [c.row_key for c in resolve_manifest(manifest)] == ["aaaa#0", "aaaa#1"]


def test_tier0_claims_carry_the_key_of_their_row_in_the_real_manifest() -> None:
    manifest = json.loads(_MANIFEST.read_text())
    seen: Counter[str] = Counter()
    expected: dict[str, list[str]] = {}
    for card in manifest["cards"]:
        cid = card["card_id"]
        expected.setdefault(cid, []).append(f"{cid}#{seen[cid]}")
        seen[cid] += 1
    claims = sweep(manifest).claims
    assert claims
    for claim in claims:
        assert claim.row_key in expected[claim.card_id]
    assert len({c.row_key for c in claims}) == len(claims)


def test_a_lone_classified_row_carries_its_real_key_and_a_keyed_claim_resolves_it() -> None:
    from pursue_index.provenance import ProvenanceTier
    from pursue_index.provenance_report import RESOLVED_BY_CLAIM, classify
    from pursue_index.resolved_claim import ResolvedClaim, ResolutionSource

    card = _card("aaaa", "first")
    assert classify(card).row_key == "aaaa#0"
    claim = ResolvedClaim(
        card_id="aaaa",
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        prior_publication="ntrs.nasa.gov",
        row_key="aaaa#0",
    )
    outcome = classify(card, external=[claim])
    assert outcome.resolved_by == RESOLVED_BY_CLAIM
    assert outcome.primary_tier == ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED.value
