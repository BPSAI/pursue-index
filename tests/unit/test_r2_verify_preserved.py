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
    """If R2 has no object at current_key → preservation copy gone."""
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
    assert "manifest-card.pdf" not in get_call_keys
    assert "preserved-card.pdf" in get_call_keys


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
