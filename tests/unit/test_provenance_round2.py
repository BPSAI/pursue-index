"""Round 2: explicit unit names, a report schema id, labelled console units, claim_count docs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pursue_index.provenance_report as provenance_report
from pursue_index.cli import provenance_cli
from pursue_index.era_bucketing import bucket, build_output
from pursue_index.provenance_report import build_report

_REPO = Path(__file__).resolve().parents[2]
_DOC = (_REPO / "docs" / "provenance-artifacts-schema.md").read_text()


def _row(card_id: str, title: str, **fields: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **fields}


_MANIFEST = {
    "cards": [
        _row("aaaa", "A1", incident_date="2022-05-06"),
        _row("aaaa", "A2", incident_date="1952-07-01"),
        _row("bbbb", "B1", incident_date="1952-07-01"),
        _row("cccc", "C1"),
        _row("cccc", "C2"),
    ]
}


def test_the_report_json_carries_its_schema_id() -> None:
    out = build_report(_MANIFEST).to_dict()
    assert provenance_report._SCHEMA == "provenance-coverage-report/v2"
    assert out["schema"] == "provenance-coverage-report/v2"
    assert "provenance-coverage-report/v2" in _DOC


def test_per_file_counts_carry_explicit_unit_names() -> None:
    buckets = build_output(_MANIFEST, bucket(_MANIFEST))
    assert "era_counts" not in buckets and "no_prior_release_count" not in buckets
    assert sum(buckets["era_file_counts"].values()) == buckets["file_count"] == 3
    assert buckets["no_prior_release_file_count"] == len(buckets["no_prior_release_files"])
    report = build_report(_MANIFEST).to_dict()
    assert "tier_counts" not in report and "tier_file_counts" in report
    for term in ("era_file_counts", "no_prior_release_file_count", "tier_file_counts"):
        assert term in _DOC


def test_file_count_is_the_same_in_both_artifacts_from_one_manifest() -> None:
    buckets = build_output(_MANIFEST, bucket(_MANIFEST))
    assert buckets["file_count"] == build_report(_MANIFEST).to_dict()["file_count"] == 3


def test_the_console_headline_and_body_use_one_labelled_unit(monkeypatch) -> None:
    from rich.console import Console

    console = Console(file=__import__("io").StringIO(), width=200, force_terminal=False)
    monkeypatch.setattr(provenance_cli, "console", console)
    report = build_report(_MANIFEST)
    provenance_cli._print_coverage(report)
    text = console.file.getvalue()
    assert f"{report.file_count} files" in text
    assert f"{report.card_row_count} rows" in text
    assert "cards" not in text.lower()
    table_rows = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"│\s*(prior-release claim[^│]*|era alone[^│]*|unresolved)\s*│\s*(\d+)", text)
    }
    assert sum(table_rows.values()) == report.file_count
    assert "Files" in text and "Rows" in text
    row_split = re.search(r"rows by route: claim (\d+), era (\d+), unresolved (\d+)", text)
    assert row_split and sum(map(int, row_split.groups())) == report.card_row_count


def test_the_doc_states_claim_count_for_each_claims_artifact() -> None:
    for name in ("identifier-claims.json", "tier0-manifest-claims.json", "ntrs-claims.json"):
        lines = [ln for ln in _DOC.splitlines() if name in ln and "claim_count" in ln]
        assert lines, name
        assert any("stored" in ln and "claims[]" in ln for ln in lines), name
    assert "per row" in _DOC
