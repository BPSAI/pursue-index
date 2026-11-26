"""The schema doc and the real outputs agree on every file/row count key and its unit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.ntrs_claims_load import NtrsOutcome
from pursue_index.provenance_report import build_report

_DOC = (Path(__file__).resolve().parents[2] / "docs" / "provenance-artifacts-schema.md").read_text()
_COUNT_KEY = re.compile(r"(^|_)(file|row|claim)_counts?$")
_SECTIONS = {"era-buckets.json": "## `era-buckets.json`", "coverage report": "## Coverage report"}


def _documented(heading: str) -> dict[str, str]:
    """Key -> unit for every table row of the section that starts at ``heading``."""
    section = _DOC.split(heading, 1)[1].split("\n## ", 1)[0]
    found: dict[str, str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 4 and cells[1].startswith("`"):
            found[cells[1].strip("`")] = cells[2]
    return found


def _manifest() -> dict[str, Any]:
    row = {"agency": "DOW", "release_date": "5/8/2026"}
    cards = [
        {"card_id": "aaaa", "title": "A1", "incident_date": "2022-05-06", **row},
        {"card_id": "aaaa", "title": "A2", **row},
        {"card_id": "bbbb", "title": "B1", "incident_date": "1952-07-01", **row},
        {"card_id": "", "title": "N1", **row},
    ]
    return {"cards": cards, "csv_sha256": "a" * 64}


def _emitted() -> dict[str, dict[str, Any]]:
    manifest = _manifest()
    summary = NtrsOutcome([], True, "a" * 64, None).summary_fields()
    return {
        "era-buckets.json": {**build_output(manifest, bucket(manifest)), **summary},
        "coverage report": {**build_report(manifest).to_dict(), **summary},
    }


def _count_keys(out: dict[str, Any]) -> set[str]:
    return {key for key in out if _COUNT_KEY.search(key)}


def test_every_emitted_count_key_is_documented_and_vice_versa() -> None:
    for name, out in _emitted().items():
        documented = {k for k in _documented(_SECTIONS[name]) if _COUNT_KEY.search(k)}
        assert _count_keys(out) == documented, name


def test_a_documented_unit_matches_the_key_suffix() -> None:
    for name, out in _emitted().items():
        units = _documented(_SECTIONS[name])
        for key in _count_keys(out):
            unit = re.search(r"(^|_)(file|row|claim)_counts?$", key)
            expected = unit.group(2) if unit else "row"
            assert units[key] == expected, (name, key, units[key])


def test_the_parser_finds_the_tables() -> None:
    assert len(_documented(_SECTIONS["era-buckets.json"])) > 10
    assert len(_documented(_SECTIONS["coverage report"])) > 8


def test_the_documented_reconciliation_and_partition_keys_are_emitted() -> None:
    """Non-count keys the schema documents for reconciliation: top level and per record."""
    out = _emitted()
    buckets, report = out["era-buckets.json"], out["coverage report"]
    for key in ("partially_resolved_files", "file_route_counts", "row_route_counts"):
        assert key in _documented(_SECTIONS["era-buckets.json"]) and key in buckets, key
    assert "partially_resolved_files" in _documented(_SECTIONS["coverage report"])
    assert "partially_resolved_files" in report
    reconciled = next(c for c in buckets["cards"] if c["row_key"] == "aaaa#1")
    assert reconciled["era_reconciled_from"] == "aaaa#0"
    assert reconciled["date_source"] == "reconciled_from_sibling"
    record = next(r for r in buckets["no_prior_release_rows"] if r["row_key"] == "aaaa#1")
    assert record["reconciled"] is True and record["era_reconciled_from"] == "aaaa#0"
    text = " ".join(_DOC.split())
    for term in ("era_reconciled_from", "reconciled_from_sibling", "`reconciled`"):
        assert term in text, term


def test_the_documented_era_maps_carry_no_mixed_bucket() -> None:
    buckets = _emitted()["era-buckets.json"]
    assert set(buckets["era_file_counts"]) == set(buckets["era_row_counts"])
    assert "mixed" not in buckets["era_file_counts"]
