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
    raw_ocr_text,
    restamp_provenance,
    text_sha,
    write_ocr_rows,
)


def _rewrite_pages_json(tmp_path: Path, card_id: str = "card-one") -> None:
    """A re-OCR: same pages, same count, different text."""
    path = tmp_path / "pages.json"
    rows = json.loads(path.read_text())
    next(r for r in rows if r["card_id"] == card_id)["text"] += " (re-OCR'd)"
    path.write_text(json.dumps(rows))


def _publish_ocr(tmp_path: Path, card_id: str, revision: str) -> None:
    """pages.json rebuilt from the card's re-OCR'd rows."""
    path = tmp_path / "pages.json"
    rows = json.loads(path.read_text())
    for r in rows:
        if r["card_id"] == card_id:
            r["text"] = raw_ocr_text(card_id, r["page"], revision)
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
        assert row["ocr_published_sha256"] == text_sha(raw_ocr_text(row["card_id"], row["page"]))
        assert row["ocr_image_only"] is False


def test_pages_json_moved_on_without_a_rebuild_fails_on_that_page(tmp_path: Path) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    _rewrite_pages_json(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-one page 1: pages.json does not publish the OCR text this page was cleaned from" in proc.stdout
    assert "card-two" not in proc.stdout  # per page, not one file-level hash


def test_rebuild_from_unchanged_cleaned_sidecars_after_a_re_ocr_fails(tmp_path: Path) -> None:
    """The case a file-level hash cannot see: re-OCR card-two (same page
    count), publish the new OCR text, then rebuild pages-cleaned.json from
    cleaned sidecars that were never re-run. The asset now records the new
    pages.json, but its pages were cleaned from the old OCR text."""
    _setup_fixture(tmp_path, _sidecar_rows())
    write_ocr_rows(tmp_path / "ocr" / "card-two", "card-two", [1, 2], revision=" v2")
    _publish_ocr(tmp_path, "card-two", " v2")
    restamp_provenance(tmp_path)
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-two page 1: cleaned from other OCR text than the page's current OCR row" in proc.stdout
    assert "card-two page 2: cleaned from other OCR text" in proc.stdout
    # pages.json was rebuilt from the new OCR, so only the stale cleaning is reported.
    assert "does not publish" not in proc.stdout
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
            row.pop("ocr_published_sha256")

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


def test_rebuild_beside_a_stale_pages_json_fails(tmp_path: Path) -> None:
    """Re-OCR card-two and re-clean it from the new OCR rows, but leave
    pages.json publishing the old OCR text, then rebuild pages-cleaned.json
    beside that stale pages.json. Every cleaned page agrees with the OCR
    sidecar and the asset was built beside the current pages.json, yet the
    site publishes text the cleaned pages were not derived from."""
    rows_by_card = _sidecar_rows()
    _setup_fixture(tmp_path, rows_by_card)
    card_dir = tmp_path / "ocr" / "card-two"
    write_ocr_rows(card_dir, "card-two", [1, 2], revision=" v2")
    for row in rows_by_card["card-two"]:
        row["input_sha256"] = text_sha(raw_ocr_text("card-two", row["page"], " v2"))
    (card_dir / "pages_cleaned.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows_by_card["card-two"]) + "\n")
    restamp_provenance(tmp_path)  # pages.json untouched: still the old OCR text
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-two page 1: pages.json does not publish the OCR text this page was cleaned from" in proc.stdout
    assert "card-one" not in proc.stdout


def test_image_only_page_may_publish_a_vision_description_but_not_ocr_text(tmp_path: Path) -> None:
    """An image-only page (blank OCR, cleaned from empty input) is tied when
    pages.json publishes our vision description or nothing for it, and fails
    when pages.json publishes OCR text the cleaned page never saw."""
    rows_by_card = _sidecar_rows()
    _setup_fixture(tmp_path, rows_by_card)
    card_dir = tmp_path / "ocr" / "card-one"
    (card_dir / "pages.jsonl").write_text(json.dumps({"card_id": "card-one", "page": 1, "text": "<b> </b>"}) + "\n")
    rows_by_card["card-one"][0]["input_sha256"] = text_sha("<b> </b>")
    (card_dir / "pages_cleaned.jsonl").write_text(json.dumps(rows_by_card["card-one"][0]) + "\n")
    restamp_provenance(tmp_path)

    def publish(text: str) -> None:
        path = tmp_path / "pages.json"
        rows = json.loads(path.read_text())
        next(r for r in rows if r["card_id"] == "card-one")["text"] = text
        path.write_text(json.dumps(rows))

    publish("[[IMAGE-OBSERVATIONS via pursue vision pass]] a photograph of a field")
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    publish("")
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    publish("text from a later OCR run")
    proc, _ = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "card-one page 1: pages.json publishes OCR text for a page cleaned as image-only" in proc.stdout
