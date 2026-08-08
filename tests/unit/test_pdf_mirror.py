"""Unit tests for the PDF r2-mirror stage + preflight guard.

Closes the Release-4 gap: PDFs OCR'd into ``ocr/<card>/meta.json`` must be
content-addressed into the NAS-local ``r2-mirror/archive/<sha>.pdf`` the curate
clean-qc judge renders page images from, or the judge silently returns
``missing_page_image``. These tests pin the stage's idempotency + sha
verification and the fail-fast preflight.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pursue_index.release.pdf_mirror import (
    run_pdf_mirror,
    verify_pdf_mirror,
)

_PDF_BYTES = b"%PDF-1.4 fake pdf bytes for tests\n%%EOF\n"
_SHA = hashlib.sha256(_PDF_BYTES).hexdigest()


def _seed_card(
    root: Path,
    card_id: str,
    *,
    pdf_bytes: bytes | None = _PDF_BYTES,
    meta_sha: str | None = _SHA,
    filename: str = "doc.pdf",
) -> None:
    """Seed a card's NAS layout: ocr/<card>/meta.json + pdfs/<card>/<file>.pdf."""
    if meta_sha is not None:
        ocr_dir = root / "ocr" / card_id
        ocr_dir.mkdir(parents=True, exist_ok=True)
        (ocr_dir / "meta.json").write_text(
            json.dumps({"card_id": card_id, "status": "ok", "pdf_sha256": meta_sha})
        )
    if pdf_bytes is not None:
        pdf_dir = root / "pdfs" / card_id
        pdf_dir.mkdir(parents=True, exist_ok=True)
        (pdf_dir / filename).write_bytes(pdf_bytes)


def _paths(root: Path) -> dict[str, Path]:
    return {
        "ocr_root": root / "ocr",
        "pdfs_root": root / "pdfs",
        "mirror_root": root / "r2-mirror",
    }


def _mirror_file(root: Path, sha: str) -> Path:
    return root / "r2-mirror" / "archive" / f"{sha}.pdf"


# --- mirror stage ---------------------------------------------------------


def test_mirror_copies_pdf_content_addressed(tmp_path: Path) -> None:
    _seed_card(tmp_path, "cardA")
    report = run_pdf_mirror(["cardA"], **_paths(tmp_path))
    assert report.ok
    assert report.mirrored == ["cardA"]
    target = _mirror_file(tmp_path, _SHA)
    assert target.is_file()
    assert target.read_bytes() == _PDF_BYTES


def test_mirror_is_idempotent_noop_when_present(tmp_path: Path) -> None:
    _seed_card(tmp_path, "cardA")
    run_pdf_mirror(["cardA"], **_paths(tmp_path))
    # Second run: already mirrored -> present, no re-copy, still ok.
    report = run_pdf_mirror(["cardA"], **_paths(tmp_path))
    assert report.ok
    assert report.present == ["cardA"]
    assert report.mirrored == []


def test_mirror_errors_when_meta_missing(tmp_path: Path) -> None:
    # OCR never ran -> no meta.json -> no sha to key the mirror by.
    _seed_card(tmp_path, "cardA", meta_sha=None)
    report = run_pdf_mirror(["cardA"], **_paths(tmp_path))
    assert not report.ok
    assert "cardA" in report.errors


def test_mirror_errors_when_source_pdf_missing(tmp_path: Path) -> None:
    _seed_card(tmp_path, "cardA", pdf_bytes=None)
    report = run_pdf_mirror(["cardA"], **_paths(tmp_path))
    assert not report.ok
    assert "cardA" in report.errors
    assert not _mirror_file(tmp_path, _SHA).exists()


def test_mirror_refuses_on_sha_mismatch(tmp_path: Path) -> None:
    # Source PDF bytes hash to something other than meta's pdf_sha256:
    # writing archive/<meta_sha>.pdf with these bytes would mis-key the doc.
    _seed_card(tmp_path, "cardA", pdf_bytes=b"different bytes")
    report = run_pdf_mirror(["cardA"], **_paths(tmp_path))
    assert not report.ok
    assert "cardA" in report.errors
    # Nothing written under the (wrong) meta sha.
    assert not _mirror_file(tmp_path, _SHA).exists()


def test_mirror_mixed_batch_reports_per_card(tmp_path: Path) -> None:
    _seed_card(tmp_path, "ok1")
    # Distinct sha so bad1's mirror is genuinely absent (not shadowed by ok1's
    # content-addressed copy) and the missing-source error surfaces.
    _seed_card(tmp_path, "bad1", pdf_bytes=None, meta_sha="b" * 64)
    report = run_pdf_mirror(["ok1", "bad1"], **_paths(tmp_path))
    assert not report.ok
    assert report.mirrored == ["ok1"]
    assert "bad1" in report.errors


# --- preflight guard ------------------------------------------------------


def test_verify_ok_when_all_mirrored(tmp_path: Path) -> None:
    _seed_card(tmp_path, "cardA")
    run_pdf_mirror(["cardA"], **_paths(tmp_path))
    pf = verify_pdf_mirror(
        ["cardA"], ocr_root=tmp_path / "ocr", mirror_root=tmp_path / "r2-mirror"
    )
    assert pf.ok
    assert pf.missing == []


def test_verify_fails_fast_on_missing_mirror(tmp_path: Path) -> None:
    # meta exists (OCR ran) but the mirror copy was never staged -> the exact
    # R4 condition that produced silent missing_page_image verdicts.
    _seed_card(tmp_path, "cardA")
    pf = verify_pdf_mirror(
        ["cardA"], ocr_root=tmp_path / "ocr", mirror_root=tmp_path / "r2-mirror"
    )
    assert not pf.ok
    assert "cardA" in pf.missing
    assert "cardA" in pf.details


def test_verify_fails_when_meta_missing(tmp_path: Path) -> None:
    _seed_card(tmp_path, "cardA", meta_sha=None)
    pf = verify_pdf_mirror(
        ["cardA"], ocr_root=tmp_path / "ocr", mirror_root=tmp_path / "r2-mirror"
    )
    assert not pf.ok
    assert "cardA" in pf.missing


# --- worklist scoping (Release-5) -----------------------------------------
#
# The gate iterated the WHOLE worklist and demanded an
# ``r2-mirror/archive/<sha>.pdf`` for every card in it. A tranche worklist
# also carries IMG/VID/AUD cards, which have no PDF and are never OCR'd
# (the OCR stage reports ``pdf_cards=N``), so the preflight failed on cards
# that were never in its remit. Release 5 was the gate's first run against a
# worklist containing IMG cards -- R4's mirror was staged by hand.
#
# Scoping must fail CLOSED: a card the manifest doesn't cover, or one whose
# asset_type is absent, stays in scope. Only an explicitly non-PDF asset_type
# is skipped, and skips are always reported -- never silent.


def _manifest(**by_id: str) -> list[dict[str, str]]:
    return [{"card_id": cid, "asset_type": t} for cid, t in by_id.items()]


def test_select_keeps_pdf_cards_and_skips_img() -> None:
    from pursue_index.release.pdf_mirror import select_pdf_cards

    in_scope, skipped = select_pdf_cards(
        ["pdf1", "img1", "pdf2"],
        _manifest(pdf1="PDF", img1="IMG", pdf2="PDF"),
    )
    assert in_scope == ["pdf1", "pdf2"]
    assert skipped == {"img1": "IMG"}


def test_select_skips_video_and_audio_cards() -> None:
    from pursue_index.release.pdf_mirror import select_pdf_cards

    in_scope, skipped = select_pdf_cards(
        ["vid1", "aud1", "pdf1"],
        _manifest(vid1="VID", aud1="AUD", pdf1="PDF"),
    )
    assert in_scope == ["pdf1"]
    assert skipped == {"vid1": "VID", "aud1": "AUD"}


def test_select_fails_closed_for_card_absent_from_manifest() -> None:
    """An unknown card stays in scope: never silently drop what we can't classify."""
    from pursue_index.release.pdf_mirror import select_pdf_cards

    in_scope, skipped = select_pdf_cards(["ghost"], _manifest(other="PDF"))
    assert in_scope == ["ghost"]
    assert skipped == {}


def test_select_fails_closed_when_asset_type_missing() -> None:
    from pursue_index.release.pdf_mirror import select_pdf_cards

    in_scope, skipped = select_pdf_cards(
        ["untyped"], [{"card_id": "untyped", "asset_type": None}]
    )
    assert in_scope == ["untyped"]
    assert skipped == {}


def test_select_preserves_worklist_order() -> None:
    from pursue_index.release.pdf_mirror import select_pdf_cards

    in_scope, _ = select_pdf_cards(
        ["z", "img", "a"], _manifest(z="PDF", img="IMG", a="PDF")
    )
    assert in_scope == ["z", "a"]


def test_verify_passes_when_only_skipped_cards_lack_mirrors(tmp_path: Path) -> None:
    """The end-to-end shape of the Release-5 failure: 1 PDF mirrored, 1 IMG card
    with no PDF anywhere. Scoped correctly, the preflight is green."""
    from pursue_index.release.pdf_mirror import select_pdf_cards

    _seed_card(tmp_path, "pdf1")
    run_pdf_mirror(["pdf1"], **_paths(tmp_path))

    in_scope, skipped = select_pdf_cards(
        ["pdf1", "img1"], _manifest(pdf1="PDF", img1="IMG")
    )
    pf = verify_pdf_mirror(
        in_scope, ocr_root=tmp_path / "ocr", mirror_root=tmp_path / "r2-mirror"
    )
    assert pf.ok is True
    assert skipped == {"img1": "IMG"}


def test_verify_still_fails_for_unmirrored_pdf_card(tmp_path: Path) -> None:
    """Scoping must not weaken the gate: a real PDF card missing its mirror
    still fails, even in a batch that also contains skipped IMG cards."""
    from pursue_index.release.pdf_mirror import select_pdf_cards

    _seed_card(tmp_path, "pdf1")  # meta + source, but never mirrored

    in_scope, _ = select_pdf_cards(["pdf1", "img1"], _manifest(pdf1="PDF", img1="IMG"))
    pf = verify_pdf_mirror(
        in_scope, ocr_root=tmp_path / "ocr", mirror_root=tmp_path / "r2-mirror"
    )
    assert pf.ok is False
    assert pf.missing == ["pdf1"]
