"""Every summary count states one unit and equals the array it sits beside.

A file (rows sharing a ``card_id``) is the unit of a headline count; a row (one
manifest entry, keyed by ``row_key``) is the unit of a ``*_row_count``. Fixtures
for the cases; the stored era buckets and the coverage report over the stored
manifest for the real data.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pursue_index.era_bucketing as era_bucketing_module
import pursue_index.provenance_report as provenance_report_module
from pursue_index.claim_precedence import positive_claims
from pursue_index.era_bucketing import bucket, build_output, classify_rows
from pursue_index.ntrs_claims_load import resolve_ntrs_claims
from pursue_index.ntrs_source import unresolved_nasa_rows
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.tier0_sweep import sweep

_REPO = Path(__file__).resolve().parents[2]
_FBI = "This file was partially posted on the FBI vault; some pages missing."


def _row(card_id: str, title: str, **fields: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **fields}


def _fixture() -> dict[str, Any]:
    """A modern-and-undated file, a modern-and-undated file with a 2019 row, an old file, a claimed file, a lone undated row."""
    return {
        "cards": [
            _row("aaaa", "A1", incident_date="2022-05-06"),
            _row("aaaa", "A2"),
            _row("aaaa", "A3"),
            _row("bbbb", "B1", incident_date="2022-05-06"),
            _row("bbbb", "B2", incident_date="2019-03-04"),
            _row("bbbb", "B3"),
            _row("cccc", "C1", incident_date="1952-07-01"),
            _row("cccc", "C2", incident_date="1952-07-01"),
            _row("dddd", "D1", incident_date="2021-01-01", description=_FBI),
            _row("dddd", "D2", incident_date="2021-01-01", description=_FBI),
            _row("eeee", "E1"),
        ]
    }


# --- the invariant -------------------------------------------------------------

# count key -> (how it is checked, what it is checked against)
_BUCKETS: dict[str, tuple[str, str]] = {
    "card_row_count": ("rows", "cards"),
    "file_count": ("files", "cards"),
    "era_file_counts": ("sum", "file_count"),
    "era_row_counts": ("sum", "card_row_count"),
    "agency_row_counts": ("sum", "card_row_count"),
    "no_prior_release_file_count": ("ids", "no_prior_release_files"),
    "no_prior_release_row_count": ("rows", "no_prior_release_rows"),
    "superseded_by_claim_row_count": ("rows", "superseded_by_claim"),
    "claim_resolved_row_count": ("rows", "claim_resolved_rows"),
    "undated_triage_row_count": ("rows", "undated_triage"),
    "file_route_counts": ("sum", "file_count"),
    "row_route_counts": ("sum", "card_row_count"),
    "partially_resolved_file_count": ("ids", "partially_resolved_files"),
}
_REPORT: dict[str, tuple[str, str]] = {
    "card_row_count": ("sum", "row_counts"),
    "file_count": ("sum_of", "resolved_by_claim,resolved_by_era,unresolved"),
    "row_counts": ("sum", "card_row_count"),
    "tier_file_counts": ("sum", "resolved_by_claim"),
    "unresolved": ("ids", "unresolved_files"),
    "unresolved_by_era": ("sum", "unresolved"),
    "unresolved_row_count": ("rows", "unresolved_rows"),
    "page_image_flagged": ("ids", "page_image_flagged_files"),
    "partially_resolved_file_count": ("ids", "partially_resolved_files"),
}
#: Counts that summarise no array in the output (what was searched, not what is listed).
_EXEMPT = {"catalogue_rows_dropped.count", "ntrs_claims_applied_row_count", "ntrs_claims_migration_ambiguous_count"}
_ROW_NAMED = re.compile(r"_row_counts?$")


def _file_of(entry: dict[str, Any]) -> str:
    return entry["card_id"] or entry["row_key"]


def _expected(out: dict[str, Any], kind: str, target: str) -> int:
    if kind == "rows":
        return len(out[target])
    if kind == "files":
        return len({_file_of(entry) for entry in out[target]})
    if kind == "ids":
        assert len(set(out[target])) == len(out[target]), f"{target} repeats a file"
        return len(out[target])
    if kind == "sum":
        value = out[target]
        return sum(value.values()) if isinstance(value, dict) else value
    return sum(out[name] for name in target.split(","))


def _check_units(out: dict[str, Any], table: dict[str, tuple[str, str]]) -> None:
    counted = [
        f"{path}{key}"
        for path, node in (("", out), *((f"{k}.", v) for k, v in out.items() if isinstance(v, dict)))
        for key in node
        if "count" in key
    ]
    unclassified = [k for k in counted if k not in table and k not in _EXEMPT]
    assert not unclassified, f"counts with no declared unit and array: {unclassified}"
    for key, (kind, target) in table.items():
        value = out[key]
        if kind == "sum" and isinstance(value, dict):
            value = sum(value.values())
        assert value == _expected(out, kind, target), f"{key} != its {target}"
        if kind in {"rows", "files", "ids"}:
            assert bool(_ROW_NAMED.search(key)) == (kind == "rows"), f"{key} is named for the wrong unit"


def _outputs(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_output(manifest, bucket(manifest)), build_report(manifest).to_dict()


def test_every_summary_count_equals_the_array_it_summarises_on_a_fixture() -> None:
    buckets, report = _outputs(_fixture())
    _check_units(buckets, _BUCKETS)
    _check_units(report, _REPORT)


def test_every_summary_count_equals_the_array_it_summarises_on_the_stored_data() -> None:
    stored = json.loads((_REPO / "data" / "provenance" / "era-buckets.json").read_text())
    manifest = json.loads((_REPO / "data" / "manifests" / "latest.json").read_text())
    _check_units(stored, _BUCKETS)
    _check_units(build_report(manifest).to_dict(), _REPORT)


def _count_beside_a_same_named_list(out: dict[str, Any]) -> list[str]:
    """Every ``X_count`` whose sibling ``X`` is a list must equal ``len(X)``."""
    return [
        f"{key}={value} but len({key[: -len('_count')]})={len(out[key[: -len('_count')]])}"
        for key, value in out.items()
        if key.endswith("_count") and isinstance(out.get(key[: -len("_count")]), list)
        and value != len(out[key[: -len("_count")]])
    ]


def test_no_count_sits_beside_a_same_named_array_of_a_different_length() -> None:
    stored = json.loads((_REPO / "data" / "provenance" / "era-buckets.json").read_text())
    buckets, _ = _outputs(_fixture())
    assert _count_beside_a_same_named_list(buckets) == []
    assert _count_beside_a_same_named_list(stored) == []


def test_a_future_count_with_no_declared_unit_fails_the_walk() -> None:
    buckets, _ = _outputs(_fixture())
    buckets["mystery_count"] = 3
    try:
        _check_units(buckets, _BUCKETS)
    except AssertionError as exc:
        assert "mystery_count" in str(exc)
    else:
        raise AssertionError("an undeclared count passed the walk")


# --- item 1: no_prior_release_file_count equals its array ----------------------------


def test_no_prior_release_count_is_per_file_with_a_file_list_beside_the_row_list() -> None:
    manifest = {"cards": [_row("aaaa", f"A{i}", incident_date="2022-05-06") for i in range(3)]}
    out = build_output(manifest, bucket(manifest))
    assert out["no_prior_release_file_count"] == len(out["no_prior_release_files"]) == 1
    assert out["no_prior_release_files"] == ["aaaa"]
    assert out["no_prior_release_row_count"] == len(out["no_prior_release_rows"]) == 3


# --- item 2: a file whose rows land in different eras is reconciled to one -----------


def test_a_file_with_one_modern_row_and_one_undated_row_is_one_modern_file() -> None:
    manifest = {"cards": [_row("aaaa", "M1", incident_date="2022-05-06"), _row("aaaa", "M2")]}
    out = build_output(manifest, bucket(manifest))
    assert out["era_file_counts"]["2015_plus"] == 1 and out["file_count"] == 1
    assert out["era_file_counts"]["undated"] == 0 and "mixed" not in out["era_file_counts"]
    assert [r["row_key"] for r in out["no_prior_release_rows"]] == ["aaaa#0", "aaaa#1"]
    assert out["undated_triage"] == []
    assert out["era_row_counts"]["2015_plus"] == 2 and out["era_row_counts"]["undated"] == 0
    assert [c["era"] for c in out["cards"]] == ["2015_plus", "2015_plus"]


def test_a_reconciled_old_file_is_counted_once_in_the_report_and_unresolved() -> None:
    manifest = {"cards": [_row("aaaa", "M1", incident_date="1952-07-01"), _row("aaaa", "M2")]}
    report = build_report(manifest)
    assert report.file_count == 1 and report.card_row_count == 2
    assert (report.resolved_by_era, report.unresolved) == (0, 1)
    assert report.unresolved_by_era == {"pre_1970": 1}
    assert sum(report.row_counts.values()) == 2


# --- item 3: every consumer keys on row_key -------------------------------------


def test_every_consumer_yields_all_three_rows_of_a_three_row_file() -> None:
    cards = [_row("aaaa", f"A{i}", incident_date="1952-07-01", agency="NASA", description=_FBI) for i in range(3)]
    manifest = {"cards": cards}
    keys = ["aaaa#0", "aaaa#1", "aaaa#2"]
    result = bucket(manifest)
    out, report = build_output(manifest, result), build_report(manifest)
    assert [c.row_key for c in classify_rows(cards)] == keys
    assert [c["row_key"] for c in out["cards"]] == keys
    assert [o.row_key for o in report.outcomes] == keys
    assert [claim.row_key for claim in sweep(manifest).claims] == keys
    assert [key for key, _ in unresolved_nasa_rows({"cards": [{**c, "description": ""} for c in cards]})] == keys
    modern = {"cards": [_row("bbbb", f"B{i}", incident_date="2022-05-06") for i in range(3)]}
    assert [e["row_key"] for e in build_output(modern, bucket(modern))["no_prior_release_rows"]] == [
        "bbbb#0", "bbbb#1", "bbbb#2",
    ]
    assert [o["row_key"] for o in build_report({"cards": [{**c, "description": ""} for c in cards]}).to_dict()["unresolved_rows"]] == keys


def test_the_schema_docs_name_row_key_as_the_per_row_key_and_card_id_as_not_unique() -> None:
    for module in (era_bucketing_module, provenance_report_module):
        doc = " ".join((module.__doc__ or "").split())
        assert "row_key" in doc and "card_id" in doc, module.__name__
        assert "not unique" in doc, module.__name__


# --- item 4: pre-keying NTRS claims migrate once, labelled -----------------------


def _stored_claim(card_id: str, **extra: Any) -> dict[str, Any]:
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


_CARDS = [_row("a0a0a0a0a0a0a012", "N1"), _row("a0a0a0a0a0a0a012", "N2"), _row("b0b0b0b0b0b0b012", "N3")]
_FILE = "a0a0a0a0a0a0a012"


def _load(root: Path, claims: list[dict[str, Any]], schema: str = "ntrs-claims/v1") -> list[ResolvedClaim]:
    """Write a stored claims file under ``root`` and load it through the run path."""
    (root / "data" / "provenance").mkdir(parents=True)
    stored = {"schema": schema, "csv_sha256": "a" * 64, "claims": claims}
    (root / "data" / "provenance" / "ntrs-claims.json").write_text(json.dumps(stored))
    return resolve_ntrs_claims(root, {"cards": _CARDS, "csv_sha256": "a" * 64}).claims


def _reaches(claims: list[ResolvedClaim], index: int) -> int:
    card = _CARDS[index]
    row_key = f"{card['card_id']}#{0 if index == 2 else index}"
    return sum(c.source == "ntrs_metadata" for c in positive_claims(card, external=claims, row_key=row_key))


def test_an_old_shape_claim_applies_to_every_row_of_its_file_and_is_labelled(tmp_path: Path) -> None:
    claims = _load(tmp_path, [_stored_claim(_FILE)])
    assert [c.row_key for c in claims] == [f"{_FILE}#0", f"{_FILE}#1"]
    assert [c.to_dict().get("row_key_migrated_from") for c in claims] == ["card_id", "card_id"]
    assert (_reaches(claims, 0), _reaches(claims, 1), _reaches(claims, 2)) == (1, 1, 0)


def test_a_keyed_file_with_an_empty_row_key_claim_applies_to_nothing(tmp_path: Path) -> None:
    claims = _load(tmp_path, [_stored_claim(_FILE, row_key="")])
    assert [c.row_key for c in claims] == [""]
    assert all(c.to_dict().get("row_key_migrated_from") is None for c in claims)
    assert (_reaches(claims, 0), _reaches(claims, 1)) == (0, 0)


def test_an_old_shape_claim_for_a_file_not_in_the_manifest_stays_unkeyed_and_counted(tmp_path: Path) -> None:
    claims = _load(tmp_path, [_stored_claim("c0c0c0c0c0c0c012")])
    assert [c.row_key for c in claims] == [""]
    manifest = {"cards": _CARDS}
    assert build_output(manifest, bucket(manifest, extra_claims=claims))["claims_without_row_key"] == 1


def test_migrated_claims_resolve_their_rows_through_the_bucketing(tmp_path: Path) -> None:
    claims = _load(tmp_path, [_stored_claim(_FILE)])
    manifest = {"cards": [{**c, "incident_date": "2022-05-06"} for c in _CARDS]}
    result = bucket(manifest, extra_claims=claims)
    assert build_output(manifest, result)["claims_without_row_key"] == 0
    assert len(result.superseded) == 2 and len(result.claims) == 1


# --- review round 1 ---------------------------------------------------------------


def test_the_report_names_its_unresolved_rows_and_files_apart() -> None:
    report = build_report({"cards": [_row("aaaa", "A1"), _row("aaaa", "A2")]})
    out = report.to_dict()
    assert "unresolved_cards" not in out and "unresolved_card_row_count" not in out
    assert out["unresolved_row_count"] == len(out["unresolved_rows"]) == 2
    assert out["unresolved_files"] == ["aaaa"] and out["unresolved"] == 1
    assert [o.row_key for o in report.unresolved_rows()] == ["aaaa#0", "aaaa#1"]


def test_a_file_is_page_image_flagged_if_any_of_its_rows_is() -> None:
    whole = {"description": "Previously released in full."}
    cards = [
        _row("aaaa", "A1", incident_date="1952-07-01", **whole),
        _row("aaaa", "A2", incident_date="1952-07-01", description=_FBI),
    ]
    report = build_report({"cards": cards})
    assert [o.needs_page_image_comparison for o in report.outcomes] == [False, True]
    assert report.page_image_flagged == 1
    assert report.to_dict()["page_image_flagged_files"] == ["aaaa"]


def test_the_schema_doc_embeds_no_manifest_specific_file_count() -> None:
    doc = (_REPO / "docs" / "provenance-artifacts-schema.md").read_text()
    assert "nine files" not in doc and "On the current manifest" not in doc


def test_stored_and_applied_ntrs_claim_counts_differ_for_an_old_shape_file(tmp_path: Path) -> None:
    stored = [_stored_claim(_FILE)]
    claims = _load(tmp_path, stored)
    assert len(stored) == 1
    manifest = {"cards": _CARDS}
    out = build_report(manifest, extra_claims=claims).to_dict()
    assert out["ntrs_claims_applied_row_count"] == len(claims) == 2


def test_no_prior_release_files_are_keyed_by_file_key(monkeypatch) -> None:
    import pursue_index.file_counts as file_counts

    monkeypatch.setattr(file_counts, "file_key", lambda card: f"file:{card.card_id}")
    manifest = {"cards": [_row("aaaa", "A1", incident_date="2022-05-06")]}
    assert bucket(manifest).no_prior_release_files == ["file:aaaa"]
