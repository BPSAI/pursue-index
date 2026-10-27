"""A digest-bearing bundle whose ``pages-cleaned.json`` is missing or
unreadable fails the gate closed -- it never reads as "everything judged"."""

from __future__ import annotations

from pathlib import Path

from tests.integration.test_qc_coverage_staleness_gate import (
    _run_gate,
    _setup_fixture,
    _sidecar_rows,
)

MESSAGE = "digest verification unavailable"


def _remove_pages_cleaned(tmp_path: Path) -> None:
    """The asset may be written whole or chunked; remove either form."""
    for p in tmp_path.glob("pages-cleaned.json*"):
        p.unlink()


def test_missing_pages_cleaned_with_a_digest_bundle_fails_closed(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _remove_pages_cleaned(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert MESSAGE in proc.stdout


def test_unreadable_pages_cleaned_with_a_digest_bundle_fails_closed(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _remove_pages_cleaned(tmp_path)
    (tmp_path / "pages-cleaned.json").write_text("{not json")
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert MESSAGE in proc.stdout


def test_missing_pages_cleaned_with_a_legacy_bundle_still_passes(tmp_path: Path) -> None:
    import json
    _setup_fixture(tmp_path, _sidecar_rows())
    bundle_path = tmp_path / "clean-qc-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    for c in bundle["cards"]:
        c.pop("judged_pages_digest")
    bundle_path.write_text(json.dumps(bundle))
    _remove_pages_cleaned(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
