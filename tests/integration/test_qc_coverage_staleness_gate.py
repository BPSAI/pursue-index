"""End-to-end: the coverage gate catches a card whose page CONTENT drifted
without its page COUNT changing (R7C.15).

Builds a real three-card corpus through the actual builders --
``build_pages_cleaned.build`` (which stamps ``source_page_sha256``) and a
hand-built clean-QC bundle whose ``judged_pages_digest`` is computed from
those SAME committed shas, simulating a bundle judged from the sidecars
the corpus was built from. Then runs the real
``scripts/build_qc_coverage.py`` as a subprocess (the same invocation
``make rebuild-derivatives`` uses) against that fixture.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_pages_cleaned  # type: ignore[import-not-found] # noqa: E402

from pursue_index.vendor.judged_pages_digest import judged_pages_digest  # noqa: E402

CARD_IDS = ["card-one", "card-two", "card-three"]


def _write_sidecar(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _sidecar_rows() -> dict[str, list[dict]]:
    return {
        "card-one": [
            {"page": 1, "card_id": "card-one", "text_cleaned": "one page one",
             "model_id": "m", "input_sha256": "a" * 64},
        ],
        "card-two": [
            {"page": 1, "card_id": "card-two", "text_cleaned": "two page one",
             "model_id": "m", "input_sha256": "b" * 64},
            {"page": 2, "card_id": "card-two", "text_cleaned": "two page two",
             "model_id": "m", "input_sha256": "c" * 64},
        ],
        "card-three": [
            {"page": 1, "card_id": "card-three", "text_cleaned": "three page one",
             "model_id": "m", "input_sha256": "d" * 64},
        ],
    }


def _write_ocr_dir(ocr_dir: Path, rows_by_card: dict[str, list[dict]]) -> None:
    for card_id, rows in rows_by_card.items():
        _write_sidecar(ocr_dir / card_id / "pages_cleaned.jsonl", rows)


def _write_manifest(path: Path) -> None:
    path.write_text(json.dumps({
        "source_url": "https://example.test/x.csv",
        "fetched_at": "2026-09-01T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": [
            {
                "card_id": cid, "title": f"card {cid}", "agency": "FBI",
                "asset_type": "PDF",
                "asset_url": f"https://example.test/{cid}.pdf",
                "release_date": "2025-01-01", "redacted": False, "raw": {},
            }
            for cid in CARD_IDS
        ],
    }))


def _bundle_from_pages_cleaned(pages_cleaned: dict) -> dict:
    """A clean-qc bundle whose digest is computed from the SAME committed
    ``source_page_sha256`` values ``pages-cleaned.json`` carries -- i.e.
    "judged from the sidecars the corpus was built from"."""
    shas: dict[str, dict[int, str]] = {}
    for row in pages_cleaned["pages"]:
        shas.setdefault(row["card_id"], {})[row["page"]] = row["source_page_sha256"]
    return {
        "bundle_schema_version": 1,
        "generated_at": "2026-09-02T00:00:00+00:00",
        "runner_version": "0.2.0",
        "judge_model": "judge-x",
        "cards": [
            {
                "card_id": card_id,
                "page_count": len(card_shas),
                "judged_pages_digest": judged_pages_digest(card_shas.items()),
            }
            for card_id, card_shas in shas.items()
        ],
    }


def _run_gate(tmp_path: Path) -> tuple[subprocess.CompletedProcess, Path]:
    out_path = tmp_path / "qc-coverage.json"
    proc = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "build_qc_coverage.py"),
            "--manifest", str(tmp_path / "manifest.json"),
            "--bundle", str(tmp_path / "clean-qc-bundle.json"),
            "--pages", str(tmp_path / "pages.json"),
            "--pages-cleaned", str(tmp_path / "pages-cleaned.json"),
            "--observations", str(tmp_path / "observations.json"),
            "--out", str(out_path),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    return proc, out_path


def restamp_provenance(tmp_path: Path) -> None:
    """Rebuild pages-cleaned.json beside the current pages.json so the asset
    records the sha256 of the pages.json it was built against."""
    build_pages_cleaned.build(
        ocr_dir=tmp_path / "ocr", manifest_path=tmp_path / "manifest.json",
        out_path=tmp_path / "pages-cleaned.json", source_tag="t",
        pages_path=tmp_path / "pages.json",
    )


def _setup_fixture(tmp_path: Path, rows_by_card: dict[str, list[dict]]) -> dict:
    """Build the full fixture tree; returns the pages-cleaned.json payload."""
    ocr_dir = tmp_path / "ocr"
    _write_ocr_dir(ocr_dir, rows_by_card)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    pages_cleaned_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest_path,
        out_path=pages_cleaned_path, source_tag="t",
    )
    pages_cleaned = json.loads(pages_cleaned_path.read_text())
    (tmp_path / "pages.json").write_text(json.dumps([
        {"card_id": p["card_id"], "page": p["page"], "text": p["text"]}
        for p in pages_cleaned["pages"]
    ]))
    restamp_provenance(tmp_path)
    (tmp_path / "observations.json").write_text(json.dumps({"card_ids": []}))
    (tmp_path / "clean-qc-bundle.json").write_text(
        json.dumps(_bundle_from_pages_cleaned(pages_cleaned))
    )
    return pages_cleaned


def _build_canonical_pages_cleaned(tmp_path: Path, canonical: dict) -> Path:
    ocr_dir = tmp_path / "ocr"
    (ocr_dir / "canon0001").mkdir(parents=True)
    (ocr_dir / "canon0001" / "pages_cleaned.jsonl").write_text(
        canonical["pages_cleaned_jsonl"]
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "source_url": "https://example.test/x.csv",
        "fetched_at": "2026-09-01T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": [{
            "card_id": "canon0001", "title": "canon", "agency": "FBI",
            "asset_type": "PDF", "asset_url": "https://example.test/c.pdf",
            "release_date": "2025-01-01", "redacted": False, "raw": {},
        }],
    }))
    pages_cleaned_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=manifest_path,
        out_path=pages_cleaned_path, source_tag="t",
    )
    return pages_cleaned_path


def _write_canonical_gate_inputs(tmp_path: Path, canonical: dict, pages_cleaned: dict) -> None:
    (tmp_path / "pages.json").write_text(json.dumps([
        {"card_id": p["card_id"], "page": p["page"], "text": p["text"]}
        for p in pages_cleaned["pages"]
    ]))
    restamp_provenance(tmp_path)
    (tmp_path / "observations.json").write_text(json.dumps({"card_ids": []}))
    (tmp_path / "clean-qc-bundle.json").write_text(json.dumps({
        "bundle_schema_version": 1,
        "generated_at": "2026-09-02T00:00:00+00:00",
        "runner_version": "0.2.0",
        "judge_model": "judge-x",
        "cards": [{
            "card_id": "canon0001", "page_count": 2,
            "judged_pages_digest": canonical["digest"],
        }],
    }))


def test_canonical_vector_digest_matches_in_the_coverage_builder(tmp_path: Path) -> None:
    """The shared ``canonical`` test vector (pages 2 and 10), run through
    ``build_pages_cleaned.py`` and then a bundle carrying its pinned
    digest, classifies ``judged`` (not ``stale``) in the real coverage
    gate -- the same digest the vendored module computes directly
    (``test_judged_pages_digest_vendor.py``) survives the full pipeline."""
    vectors = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "judged_pages_digest_vectors.json")
        .read_text(encoding="utf-8")
    )["cases"]
    canonical = next(c for c in vectors if c["name"] == "canonical")

    pages_cleaned_path = _build_canonical_pages_cleaned(tmp_path, canonical)
    pages_cleaned = json.loads(pages_cleaned_path.read_text())
    assert {p["page"]: p["source_page_sha256"] for p in pages_cleaned["pages"]} == {
        int(page): sha for page, sha in canonical["page_shas"].items()
    }
    _write_canonical_gate_inputs(tmp_path, canonical, pages_cleaned)

    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(out_path.read_text())
    assert doc["status_counts"] == {
        "judged": 1, "partially_judged": 0, "stale": 0,
        "unverified_transcript": 0, "review": 0, "unverified_vision": 0,
        "no_text": 0, "unverified_other": 0,
    }


def test_legacy_bundle_without_digests_prints_a_one_line_notice(tmp_path: Path) -> None:
    pages_cleaned = _setup_fixture(tmp_path, _sidecar_rows())
    # Strip the digest field the fixture bundle would otherwise carry --
    # simulates a bundle published before R7C.15.
    bundle = json.loads((tmp_path / "clean-qc-bundle.json").read_text())
    for card in bundle["cards"]:
        del card["judged_pages_digest"]
    (tmp_path / "clean-qc-bundle.json").write_text(json.dumps(bundle))

    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no judged_pages_digest field" in proc.stdout
    doc = json.loads(out_path.read_text())
    assert doc["bundle_missing_digests"] is True
    assert doc["status_counts"]["judged"] == len(pages_cleaned["meta"]["cards_covered"])
    assert doc["status_counts"]["stale"] == 0


def test_an_unchanged_corpus_rebuilt_from_the_same_sidecars_has_zero_stale_cards(
    tmp_path: Path,
) -> None:
    _setup_fixture(tmp_path, _sidecar_rows())
    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(out_path.read_text())
    assert doc["status_counts"]["stale"] == 0
    assert doc["status_counts"]["judged"] == 3


def test_one_changed_page_fails_the_gate_on_the_stale_card(tmp_path: Path) -> None:
    rows_by_card = _sidecar_rows()
    _setup_fixture(tmp_path, rows_by_card)

    # A re-OCR/re-clean changes card-two's page 1 text, but not its page
    # count. Rebuild pages-cleaned.json from the mutated sidecar; the
    # bundle (judged against the ORIGINAL text) is left as-is.
    rows_by_card["card-two"][0]["text_cleaned"] = "two page one, RE-OCR'd"
    ocr_dir = tmp_path / "ocr"
    _write_sidecar(ocr_dir / "card-two" / "pages_cleaned.jsonl", rows_by_card["card-two"])
    pages_cleaned_path = tmp_path / "pages-cleaned.json"
    build_pages_cleaned.build(
        ocr_dir=ocr_dir, manifest_path=tmp_path / "manifest.json",
        out_path=pages_cleaned_path, source_tag="t",
    )
    pages_cleaned = json.loads(pages_cleaned_path.read_text())
    (tmp_path / "pages.json").write_text(json.dumps([
        {"card_id": p["card_id"], "page": p["page"], "text": p["text"]}
        for p in pages_cleaned["pages"]
    ]))
    restamp_provenance(tmp_path)

    proc, out_path = _run_gate(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "stale card-two" in proc.stdout
    doc = json.loads(out_path.read_text())
    assert doc["status_counts"]["stale"] == 1
    stale = [c["card_id"] for c in doc["cards"] if c["status"] == "stale"]
    assert stale == ["card-two"]
    # The other two cards' content is untouched -- still judged.
    assert doc["status_counts"]["judged"] == 2
