"""The coverage gate proves pages-cleaned.json was built from the current
pages.json: a same-page-count re-OCR behind a stale cleaned asset fails."""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.test_qc_coverage_staleness_gate import (
    _run_gate,
    _setup_fixture,
    _sidecar_rows,
)


def _rewrite_pages_json(tmp_path: Path) -> None:
    """A re-OCR: same pages, same count, different text."""
    path = tmp_path / "pages.json"
    rows = json.loads(path.read_text())
    rows[0]["text"] += " (re-OCR'd)"
    path.write_text(json.dumps(rows))


def test_matching_provenance_passes(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_stale_cleaned_asset_fails_with_both_shas(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    recorded = json.loads((tmp_path / "pages-cleaned.json").read_text())["meta"]["pages_json_sha256"]
    _rewrite_pages_json(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "cleaned asset stale: rebuilt from " + recorded[:12] in proc.stdout
    assert ", current " in proc.stdout


def test_legacy_cleaned_asset_without_provenance_fails_closed(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    doc = json.loads((tmp_path / "pages-cleaned.json").read_text())
    doc["meta"].pop("pages_json_sha256")
    for p in tmp_path.glob("pages-cleaned.json*"):
        p.unlink()
    (tmp_path / "pages-cleaned.json").write_text(json.dumps(doc))
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "provenance unavailable" in proc.stdout


def test_a_legacy_bundle_without_digests_needs_no_provenance(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    bundle_path = tmp_path / "clean-qc-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    for c in bundle["cards"]:
        c.pop("judged_pages_digest")
    bundle_path.write_text(json.dumps(bundle))
    _rewrite_pages_json(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
