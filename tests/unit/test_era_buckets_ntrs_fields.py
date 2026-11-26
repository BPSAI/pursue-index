"""era-buckets.json records whether NTRS claims were applied, from the run's own outcome."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from pursue_index import era_bucketing, ntrs_source
from tests.support.ntrs_fakes import Net, Resp, card, variant

EARLY = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
SHA = "a" * 64


def _manifest(sha: str) -> dict[str, Any]:
    return {"cards": [card(incident_date="2020")], "csv_sha256": sha, "source_url": "https://example.test/m"}


def _write_manifest(root: Path, sha: str) -> None:
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "data" / "manifests" / "latest.json").write_text(json.dumps(_manifest(sha)))


def _bucketed(
    root: Path, monkeypatch: pytest.MonkeyPatch, manifest_sha: str, *, claims: str = "make"
) -> dict[str, Any]:
    if claims != "none":
        _write_manifest(root, SHA)
        hosts = root / "data" / "provenance" / "ntrs-hosts.json"
        hosts.parent.mkdir(parents=True, exist_ok=True)
        hosts.write_text(json.dumps({"hosts": ["ntrs.nasa.gov"]}))
        ntrs_source.run(root, Net(Resp(200, EARLY)).fetcher(), datetime.date(2026, 11, 25))
        if claims == "strip":
            path = root / ntrs_source.OUTPUT_PATH
            data = json.loads(path.read_text())
            data.pop("csv_sha256", None)
            path.write_text(json.dumps(data))
    _write_manifest(root, manifest_sha)
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(root))
    assert era_bucketing.main() == 0
    return json.loads((root / era_bucketing.OUTPUT_PATH).read_text())


def test_matching_claims_record_applied_and_the_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _bucketed(tmp_path, monkeypatch, SHA)
    assert out.get("ntrs_claims_applied") is True
    assert out.get("ntrs_claims_csv_sha256", "<absent>") == SHA


def test_stale_claims_record_not_applied_and_the_claims_file_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _bucketed(tmp_path, monkeypatch, "b" * 64)
    assert out.get("ntrs_claims_applied") is False
    assert out.get("ntrs_claims_csv_sha256", "<absent>") == SHA


def test_a_claims_file_without_a_marker_records_false_and_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _bucketed(tmp_path, monkeypatch, SHA, claims="strip")
    assert out.get("ntrs_claims_applied") is False
    assert out.get("ntrs_claims_csv_sha256", "<absent>") is None


def test_no_claims_file_records_false_and_null(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _bucketed(tmp_path, monkeypatch, SHA, claims="none")
    assert out.get("ntrs_claims_applied") is False
    assert out.get("ntrs_claims_csv_sha256", "<absent>") is None


def test_other_keys_and_entries_are_unchanged_and_output_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _bucketed(tmp_path, monkeypatch, "b" * 64, claims="none")
    first = (tmp_path / era_bucketing.OUTPUT_PATH).read_text()
    assert era_bucketing.main() == 0
    assert (tmp_path / era_bucketing.OUTPUT_PATH).read_text() == first
    extra = {"ntrs_claims_applied", "ntrs_claims_csv_sha256"}
    assert list(out)[: len(out) - len(extra & set(out))] == [k for k in out if k not in extra]
    assert [k for k in out if k not in extra] == [
        "schema", "corpus_manifest_url", "csv_sha256", "card_row_count", "catalogue_entries",
        "catalogue_rows_dropped", "file_count", "era_counts", "era_row_counts", "agency_row_counts",
        "reconciliation_4a", "no_prior_release_count", "no_prior_release_files",
        "no_prior_release_row_count", "claims_without_row_key", "no_prior_release_rows",
        "superseded_by_claim_row_count", "superseded_by_claim", "undated_triage_row_count",
        "undated_triage", "cards",
    ]
    assert out["card_row_count"] == len(out["cards"]) == 1
