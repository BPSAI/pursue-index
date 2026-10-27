"""A digest-bearing bundle whose ``pages-cleaned.json`` is missing or
unreadable fails the gate closed -- it never reads as "everything judged"."""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.release.chunked_asset import read_asset_json, write_asset
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
    _setup_fixture(tmp_path, _sidecar_rows())
    bundle_path = tmp_path / "clean-qc-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    for c in bundle["cards"]:
        c.pop("judged_pages_digest")
    bundle_path.write_text(json.dumps(bundle))
    _remove_pages_cleaned(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _drop_a_page_sha(tmp_path: Path, card_id: str) -> None:
    """Leave ``card_id`` one page short in pages-cleaned.json; others complete."""
    doc = read_asset_json(tmp_path / "pages-cleaned.json")
    dropped = False
    kept = []
    for row in doc["pages"]:
        if row["card_id"] == card_id and not dropped:
            dropped = True
            continue
        kept.append(row)
    doc["pages"] = kept
    _remove_pages_cleaned(tmp_path)
    (tmp_path / "pages-cleaned.json").write_text(json.dumps(doc))


def _chunk_the_bundle(tmp_path: Path) -> None:
    path = tmp_path / "clean-qc-bundle.json"
    data = path.read_bytes()
    path.unlink()
    write_asset(path, data, budget=200)
    assert not path.exists() and (tmp_path / "clean-qc-bundle.json.chunks.json").exists()


def test_one_card_with_incomplete_shas_fails_the_gate_while_others_are_complete(
    tmp_path: Path,
) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _drop_a_page_sha(tmp_path, "card-two")
    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert MESSAGE in proc.stdout
    assert "card-two" in proc.stdout
    assert "card-one" not in proc.stdout and "card-three" not in proc.stdout


def test_complete_shas_for_every_digest_card_still_pass(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_chunked_bundle_is_read_and_still_gated(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _chunk_the_bundle(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_chunked_bundle_with_incomplete_shas_fails_closed_not_open(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _drop_a_page_sha(tmp_path, "card-two")
    _chunk_the_bundle(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert MESSAGE in proc.stdout


def test_a_partially_judged_card_is_not_a_verification_gap(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    bundle_path = tmp_path / "clean-qc-bundle.json"
    bundle = json.loads(bundle_path.read_text())
    next(c for c in bundle["cards"] if c["card_id"] == "card-two")["page_count"] = 1
    bundle_path.write_text(json.dumps(bundle))
    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(out_path.read_text())["status_counts"]["partially_judged"] == 1
