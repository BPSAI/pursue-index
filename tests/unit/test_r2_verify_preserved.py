"""Tests for ``scripts/r2_verify_preserved.py``.

The verify-preserved script extends the daily integrity sweep to cover
``/removed`` preservation copies. Unlike the manifest-walking verify
(which HEADs upstream to detect silent overlays), this one re-reads
R2 itself and compares against the registry's pinned byte_sha — for
preserved cards the upstream URL is no longer authoritative (it's
either 404 or now serves a replacement file).

A mismatch here means **something tampered with the preservation copy
in R2 itself** — buggy script, compromised key, accidental wrangler
PUT. Different alert from the silent-overlay-detected case.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import r2_verify_preserved  # noqa: E402


_GOOD_BYTES = b"%PDF-1.4 preserved bytes"
_GOOD_SHA = "5b8b1c3e0a9c0f8b67e54bc3d3a91dffd935f15f8c5e09cbcf78bee75ba9c4f5"
# Computed once and pinned — if the test bytes ever change, update both.

import hashlib  # noqa: E402

_ACTUAL_GOOD_SHA = hashlib.sha256(_GOOD_BYTES).hexdigest()


def _preserved_row(card_id: str = "abc123", byte_sha: str | None = None) -> dict:
    return {
        "card_id": card_id,
        "asset_filename": "doc.pdf",
        "byte_sha256": byte_sha or _ACTUAL_GOOD_SHA,
        "byte_size": len(_GOOD_BYTES),
        "archive_key": f"archive/{byte_sha or _ACTUAL_GOOD_SHA}.pdf",
        "current_key": f"{card_id}.pdf",
        "fetched_at": "2026-05-12T14:44:09+00:00",
        "preserved": True,
    }


def _non_preserved_row(card_id: str = "manifest-card") -> dict:
    row = _preserved_row(card_id)
    del row["preserved"]
    return row


def _fake_get(body: bytes) -> dict:
    obj = MagicMock()
    obj.read.return_value = body
    return {"Body": obj, "ContentLength": len(body)}


def test_verify_passes_when_bytes_match_registry() -> None:
    """Happy path: R2 bytes hash to the registry's pinned byte_sha."""
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    registry = {"abc123": [_preserved_row("abc123")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == ["abc123"]
    assert report["mismatch"] == []
    assert report["missing"] == []


def test_verify_flags_byte_sha_mismatch() -> None:
    """If R2 bytes don't hash to the pinned sha → tampering detected."""
    client = MagicMock()
    client.get_object.return_value = _fake_get(b"%PDF-1.4 TAMPERED bytes")

    registry = {"abc123": [_preserved_row("abc123")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == []
    assert len(report["mismatch"]) == 1
    mm = report["mismatch"][0]
    assert mm["card_id"] == "abc123"
    assert mm["expected_sha"] == _ACTUAL_GOOD_SHA
    assert mm["actual_sha"] != _ACTUAL_GOOD_SHA


def test_verify_flags_missing_object() -> None:
    """If R2 has no object at archive_key → preservation copy gone."""
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
        "GetObject",
    )

    registry = {"abc123": [_preserved_row("abc123")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == []
    assert report["mismatch"] == []
    assert report["missing"] == ["abc123"]


def test_verify_skips_non_preserved_rows() -> None:
    """The manifest-walking verify covers non-preserved rows; skip them here."""
    client = MagicMock()
    registry = {
        "manifest-card": [_non_preserved_row("manifest-card")],
        "preserved-card": [_preserved_row("preserved-card")],
    }
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == ["preserved-card"]
    # Manifest card was never read — verify-preserved doesn't touch it.
    get_call_keys = [c.kwargs.get("Key") for c in client.get_object.call_args_list]
    assert f"archive/{_ACTUAL_GOOD_SHA}.pdf" in get_call_keys
    # Neither current_key form (manifest-card.pdf / preserved-card.pdf)
    # is read — we only read the archive key, regardless of card_id.
    assert "manifest-card.pdf" not in get_call_keys
    assert "preserved-card.pdf" not in get_call_keys


def test_verify_skips_row_missing_archive_key(capsys) -> None:
    """Sprint 4a fix-pass (nayru coverage gap): a preserved row that
    lacks ``archive_key`` is skipped with a warning, not a KeyError.

    Registry rows are merged from multiple writers (the daily ingest,
    operator-triggered re-pins, the Section 6 reaffirmation script).
    A row produced by a pre-Sprint-4a writer might lack the
    ``archive_key`` field even though ``preserved=True``. The verify
    must surface that as a triageable warning rather than crash the
    daily integrity sweep.
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    row = _preserved_row("legacy-card")
    del row["archive_key"]  # legacy writer never populated it
    registry = {"legacy-card": [row]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    # The row is skipped — not counted as ok/mismatch/missing — and a
    # warning is emitted so the operator sees the schema gap.
    assert report["ok"] == []
    assert report["mismatch"] == []
    assert report["missing"] == []
    captured = capsys.readouterr()
    assert "legacy-card" in captured.out
    assert "archive_key" in captured.out


def test_verify_reads_archive_key_not_current_key() -> None:
    """The verify must read archive/<sha>.<ext>, not current_key.

    Sprint 4a (2026-05-17): The Section 6 (2026-05-14 preserved-pin
    reaffirmation) policy means current_key legitimately serves NEW
    upstream bytes while the OLD preserved bytes live at
    archive/<preserved_sha>.<ext>. Reading current_key produces
    false-positive mismatches every day for the Section 6 cards
    (Issues #61, #64). Reading archive_key directly verifies what
    "preservation" structurally means.
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    row = _preserved_row("card-x")
    # The Section-6 case: current_key may serve different bytes than
    # the pinned byte_sha. archive_key always serves the pinned bytes.
    registry = {"card-x": [row]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == ["card-x"]
    # The get_object call must have used archive_key, not current_key.
    call = client.get_object.call_args
    assert call.kwargs["Key"] == row["archive_key"]
    assert call.kwargs["Key"] != row["current_key"]


def test_verify_section6_reaffirmation_no_longer_false_positives() -> None:
    """Reproduces the Section-6 false-positive case: archive/<sha>.<ext>
    holds the preserved bytes intact (verify passes); current_key holds
    different upstream bytes (would have falsely flagged tampering
    under the old current_key-based check).

    We only exercise the archive_key read here — the script no longer
    touches current_key, so the bytes there are irrelevant to the
    verify. Asserts the script reports ok, not mismatch.
    """
    client = MagicMock()
    # R2 returns the preserved (good) bytes when asked for archive_key.
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    registry = {"section6-card": [_preserved_row("section6-card")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    # Critical: under the OLD logic this would have appeared as a
    # mismatch (current_key serving new upstream bytes). Under the
    # NEW logic it's clean — we verified the immutable archive copy.
    assert report["ok"] == ["section6-card"]
    assert report["mismatch"] == []
    assert report["missing"] == []


def test_verify_mismatch_report_uses_archive_key_field() -> None:
    """When a mismatch fires, the report names archive_key (not current_key).

    Renamed in Sprint 4a so an operator reading the issue body sees
    the actual key that failed — the immutable preservation copy at
    archive/<sha>.<ext> — not the mutable current-pointer.
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(b"%PDF-1.4 TAMPERED bytes")
    row = _preserved_row("tampered-card")
    registry = {"tampered-card": [row]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert len(report["mismatch"]) == 1
    mm = report["mismatch"][0]
    assert "archive_key" in mm
    assert mm["archive_key"] == row["archive_key"]
    # current_key is intentionally not present — it's not what was read.
    assert "current_key" not in mm


def test_verify_uses_most_recent_registry_row_per_card() -> None:
    """Multiple rows per card_id: verify against the newest preserved row.

    If a preservation copy was re-pinned (e.g., bytes intentionally
    updated by operator action with a new registry row appended), the
    verify should compare against the latest pinned sha, not the first.
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    stale = _preserved_row("abc123", byte_sha="0" * 64)
    fresh = _preserved_row("abc123", byte_sha=_ACTUAL_GOOD_SHA)
    fresh["fetched_at"] = "2026-06-01T00:00:00+00:00"
    registry = {"abc123": [stale, fresh]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == ["abc123"]
    assert report["mismatch"] == []


# --- Sprint 4b Theme C — video row coverage ---------------------------
#
# VID cards live at DVIDS, not war.gov. The bytes were preserved into
# R2 once (when first ingested) but VID rows in the registry carry no
# ``current_key`` (the worker serves video via DVIDS iframe, not from
# R2). They DO carry an ``archive_key`` and a ``byte_sha256`` — the
# preservation copy is real and verifiable. The pre-Sprint-4b verify
# only considered rows with ``preserved=True`` and silently dropped
# every VID row (none of which carry that flag — see the existing 28
# rows in data/asset-bytes-registry.jsonl). That's the gap this theme
# closes.


def _vid_row(card_id: str = "vid-1", byte_sha: str | None = None) -> dict:
    """A video registry row matching the existing on-disk schema.

    Per data/asset-bytes-registry.jsonl: VID rows carry ``archive_key``
    + ``dvids_video_id`` + ``source`` but NOT ``current_key`` (no R2
    serving path because the worker doesn't serve videos from R2) and
    NOT ``preserved`` (the historical writer didn't set it).
    """
    sha = byte_sha or _ACTUAL_GOOD_SHA
    return {
        "card_id": card_id,
        "asset_filename": f"{card_id}.mp4",
        "dvids_video_id": "8642001",
        "asset_url": "https://www.dvidshub.net/video/865432/example",
        "byte_sha256": sha,
        "byte_size": len(_GOOD_BYTES),
        "archive_key": f"archive/{sha}.mp4",
        "fetched_at": "2026-05-08T18:12:00+00:00",
        "source": "dvids-ingest",
        "dod_asset_filename": "example.mp4",
    }


def test_verify_walks_video_rows_even_without_preserved_flag() -> None:
    """VID rows (no current_key, no preserved flag) must still be verified.

    Pre-Sprint-4b: ``_latest_preserved_row`` only returned rows where
    ``preserved is True``. VID rows have neither ``current_key`` nor
    ``preserved=True``, so the verify silently skipped all 28 of them.
    Post-Sprint-4b: a row lacking ``current_key`` is treated as an
    implicit preservation row (the worker doesn't serve it; R2 is the
    only canonical bytes home).
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    registry = {"vid-1": [_vid_row("vid-1")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == ["vid-1"]
    # The verify must have read the archive_key for the VID row.
    call = client.get_object.call_args
    assert call.kwargs["Key"] == _vid_row("vid-1")["archive_key"]


def test_verify_flags_video_byte_sha_mismatch() -> None:
    """Tampered VID preservation bytes surface as a mismatch entry."""
    client = MagicMock()
    client.get_object.return_value = _fake_get(b"tampered video bytes")

    registry = {"vid-2": [_vid_row("vid-2")]}
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert report["ok"] == []
    assert len(report["mismatch"]) == 1
    mm = report["mismatch"][0]
    assert mm["card_id"] == "vid-2"
    assert mm["archive_key"].startswith("archive/")
    assert mm["archive_key"].endswith(".mp4")


def test_verify_walks_vid_row_with_explicit_preserved_false() -> None:
    """nayru P2#3: ``preserved=False`` row WITHOUT ``current_key`` still walked.

    The Sprint 4b Theme C eligibility rule is:

        row.get('preserved') is True or row.get('current_key') is None

    A pre-existing VID row in the registry might carry
    ``preserved: false`` explicitly (e.g. set by a future writer
    that flips the flag) yet still lack a ``current_key`` (VIDs are
    served via DVIDS iframe; the worker has no R2 serving path).
    Under the OR semantics, that row IS preservation-eligible — the
    no-current_key branch fires regardless of the ``preserved``
    value. This locks the semantics so a future "simplification"
    that drops the OR to a single ``preserved is True`` check would
    fail visibly.
    """
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    row = _vid_row("vid-explicit-false")
    row["preserved"] = False  # explicit, not just missing
    assert "current_key" not in row  # the load-bearing condition
    registry = {"vid-explicit-false": [row]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    # Row IS walked: archive_key was read and matched the pinned
    # byte_sha. ``preserved: False`` doesn't disqualify when
    # ``current_key`` is absent.
    assert report["ok"] == ["vid-explicit-false"]
    assert report["mismatch"] == []
    assert report["missing"] == []


def test_verify_walks_video_and_pdf_rows_together() -> None:
    """A mixed registry (VID + PDF preserved) is fully walked, all-ok."""
    client = MagicMock()
    client.get_object.return_value = _fake_get(_GOOD_BYTES)

    registry = {
        "pdf-card": [_preserved_row("pdf-card")],
        "vid-card": [_vid_row("vid-card")],
    }
    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    assert sorted(report["ok"]) == ["pdf-card", "vid-card"]
    assert report["mismatch"] == []
    assert report["missing"] == []


def test_verify_skips_manifest_only_rows_with_current_key_and_no_preserved() -> None:
    """Manifest-walking (PDF/IMG with current_key) is the daily HEAD-verify lane.

    A row with ``current_key`` set but ``preserved`` unset belongs to
    the live manifest — the silent-overlay-detected workflow covers
    it. The verify-preserved lane must NOT walk it, or every daily
    sweep would re-hash the entire archive twice.
    """
    client = MagicMock()
    registry = {"manifest-card": [_non_preserved_row("manifest-card")]}

    report = r2_verify_preserved.verify_preserved(
        registry=registry, client=client, bucket="pursue-pdfs"
    )

    # Skipped: not preserved, has current_key (manifest-walking covers it).
    assert report["ok"] == []
    assert report["mismatch"] == []
    assert report["missing"] == []
    assert client.get_object.call_count == 0
