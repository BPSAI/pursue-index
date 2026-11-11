"""The coverage gate ties every judged cleaned page, per page, to the OCR
text published now: a same-page-count re-OCR behind a stale cleaned asset
fails, whether pages.json moved on without a rebuild or the asset was
rebuilt from cleaned sidecars that predate the re-OCR."""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.test_qc_coverage_staleness_gate import (
    _run_gate,
    _setup_fixture,
    _sidecar_rows,
    restamp_provenance,
    write_ocr_rows,
)


def _rewrite_pages_json(tmp_path: Path, card_id: str = "card-one") -> None:
    """A re-OCR: same pages, same count, different text."""
    path = tmp_path / "pages.json"
    rows = json.loads(path.read_text())
    next(r for r in rows if r["card_id"] == card_id)["text"] += " (re-OCR'd)"
    path.write_text(json.dumps(rows))


def _rewrite_cleaned(tmp_path: Path, edit) -> None:
    doc = json.loads((tmp_path / "pages-cleaned.json").read_text())
    for p in tmp_path.glob("pages-cleaned.json*"):
        p.unlink()
    edit(doc)
    (tmp_path / "pages-cleaned.json").write_text(json.dumps(doc))


def test_matching_provenance_passes(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_builder_records_per_page_provenance(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    doc = json.loads((tmp_path / "pages-cleaned.json").read_text())
    for row in doc["pages"]:
        assert row["ocr_page_sha256"] == row["input_sha256"]
        assert len(row["pages_json_text_sha256"]) == 64


def test_pages_json_moved_on_without_a_rebuild_fails_on_that_page(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _rewrite_pages_json(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-one page 1: pages.json text changed since pages-cleaned.json was built" in proc.stdout
    assert "card-two" not in proc.stdout  # per page, not one file-level hash


def test_rebuild_from_unchanged_cleaned_sidecars_after_a_re_ocr_fails(tmp_path: Path) -> None:
    """The case a file-level hash cannot see: re-OCR card-two (same page
    count), publish the new OCR text, then rebuild pages-cleaned.json from
    cleaned sidecars that were never re-run. The asset now records the new
    pages.json, but its pages were cleaned from the old OCR text."""
    _setup_fixture(tmp_path, _sidecar_rows())
    write_ocr_rows(tmp_path / "ocr" / "card-two", "card-two", [1, 2], revision=" v2")
    _rewrite_pages_json(tmp_path, "card-two")
    restamp_provenance(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-two page 1: cleaned from other OCR text than the page's current OCR row" in proc.stdout
    assert "card-two page 2: cleaned from other OCR text" in proc.stdout
    assert "pages.json text changed" not in proc.stdout  # the rebuild recorded the new text
    assert "card-one" not in proc.stdout


def test_an_unrelated_pages_json_change_does_not_fail_judged_cards(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    path = tmp_path / "pages.json"
    rows = json.loads(path.read_text())
    rows.append({"card_id": "card-unjudged", "page": 1, "text": "a new tranche page"})
    path.write_text(json.dumps(rows))
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cleaned_asset_without_per_page_provenance_fails_closed(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())

    def strip(doc: dict) -> None:
        for row in doc["pages"]:
            row.pop("ocr_page_sha256")
            row.pop("pages_json_text_sha256")

    _rewrite_cleaned(tmp_path, strip)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-one page 1: no per-page provenance (rebuild pages-cleaned.json)" in proc.stdout


def test_a_malformed_row_is_named_and_does_not_mask_the_other_cards(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())

    def corrupt(doc: dict) -> None:
        doc["pages"].append({"card_id": "card-one", "page": "seven", "source_page_sha256": "f" * 64})

    _rewrite_cleaned(tmp_path, corrupt)
    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "pages-cleaned.json pages[4]: card-one: page 'seven' is not an integer" in proc.stdout
    assert "page sha(s) for" not in proc.stdout  # every card's shas survived the bad row
    doc = json.loads(out_path.read_text())
    assert doc["status_counts"]["judged"] == 3


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
