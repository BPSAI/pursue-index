"""Tests for ``scripts/r2_pin_removed.py``.

The pin script retroactively brings ``/removed`` preservation copies
under the integrity layer's coverage. Before pinning, those bytes live
in R2 only at ``<card_id>.<ext>`` (the May 8 manual-upload keys) with
no append-only ``archive/<sha>.<ext>`` counterpart and no registry row
— meaning the daily byte-verify cron has nothing to diff against, so
a silent overwrite of a preserved copy would be undetectable.

These tests pin the contract that:

  * idempotent re-runs are a no-op (registry-row presence is the gate)
  * IfNoneMatch on the archive PUT keeps the layer append-only even if
    a future run computes the same byte_sha
  * the registry row carries a ``preserved: true`` flag so the verify
    cron can distinguish "manifest-current card" from "preservation
    copy" and never expect upstream HEADs to succeed for the latter
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import r2_pin_removed  # noqa: E402

_FAKE_PDF_BYTES = b"%PDF-1.4 fake bytes for testing"
_FAKE_PDF_SHA = hashlib.sha256(_FAKE_PDF_BYTES).hexdigest()


def _removed_card(card_id: str, asset_filename: str = "doc.pdf") -> dict:
    """Minimal removed-cards.json entry shape."""
    return {
        "detected_at": "2026-05-12T00:00:00+00:00",
        "prior_csv_sha256": "deadbeef" * 8,
        "new_csv_sha256": "cafe" * 16,
        "prior_fetched_at": "2026-05-08T21:00:46.185453Z",
        "card": {
            "card_id": card_id,
            "title": "Test Card",
            "asset_type": "PDF",
            "asset_filename": asset_filename,
            "asset_url": "https://www.war.gov/medialink/ufo/release_1/doc.pdf",
        },
    }


def _fake_get_object(body: bytes) -> dict:
    """Shape of a boto3 get_object response — Body has .read()."""
    body_obj = MagicMock()
    body_obj.read.return_value = body
    return {"Body": body_obj, "ContentLength": len(body)}


def test_pin_writes_archive_and_registry_for_unpinned_card(tmp_path: Path) -> None:
    """First-time pin: GETs from R2, computes sha, PUTs archive key, writes registry row."""
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": len(_FAKE_PDF_BYTES)}
    client.get_object.return_value = _fake_get_object(_FAKE_PDF_BYTES)

    registry_path = tmp_path / "registry.jsonl"
    card = _removed_card("abc1230000000001")

    result = r2_pin_removed.pin_card(
        card_entry=card,
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=registry_path,
        dry_run=False,
    )

    assert result == "pinned"
    # Archive PUT MUST use IfNoneMatch to stay append-only.
    put_kwargs = client.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == "pursue-pdfs"
    assert put_kwargs["Key"] == f"archive/{_FAKE_PDF_SHA}.pdf"
    assert put_kwargs["IfNoneMatch"] == "*"
    assert put_kwargs["Body"] == _FAKE_PDF_BYTES

    # Registry row landed with preserved: true.
    rows = [json.loads(ln) for ln in registry_path.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["card_id"] == "abc1230000000001"
    assert row["byte_sha256"] == _FAKE_PDF_SHA
    assert row["byte_size"] == len(_FAKE_PDF_BYTES)
    assert row["archive_key"] == f"archive/{_FAKE_PDF_SHA}.pdf"
    assert row["current_key"] == "abc1230000000001.pdf"
    assert row["preserved"] is True
    assert "fetched_at" in row


def test_pin_skips_card_already_in_registry(tmp_path: Path) -> None:
    """Idempotency gate: registry row presence → skip everything."""
    client = MagicMock()
    registry_path = tmp_path / "registry.jsonl"
    registry = {
        "abc1230000000001": [
            {
                "card_id": "abc1230000000001",
                "byte_sha256": _FAKE_PDF_SHA,
                "preserved": True,
                "fetched_at": "2026-05-12T00:00:00+00:00",
            }
        ]
    }

    result = r2_pin_removed.pin_card(
        card_entry=_removed_card("abc1230000000001"),
        client=client,
        bucket="pursue-pdfs",
        registry=registry,
        registry_path=registry_path,
        dry_run=False,
    )

    assert result == "already-pinned"
    client.get_object.assert_not_called()
    client.put_object.assert_not_called()
    assert not registry_path.exists()


def test_pin_idempotent_when_archive_key_exists_but_registry_missing(
    tmp_path: Path,
) -> None:
    """Recovery path: archive key in R2 but no registry row → write row, skip PUT.

    Could happen if a previous pin run wrote the archive PUT but crashed
    before appending the registry row. The IfNoneMatch on the archive
    PUT will fail with PreconditionFailed; we catch that, treat the
    archive as already-pinned, and still write the registry row so the
    daily verify cron picks the card up.
    """
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    client = MagicMock()
    client.head_object.return_value = {"ContentLength": len(_FAKE_PDF_BYTES)}
    client.get_object.return_value = _fake_get_object(_FAKE_PDF_BYTES)
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed", "Message": "If-None-Match failed"}},
        "PutObject",
    )

    registry_path = tmp_path / "registry.jsonl"
    result = r2_pin_removed.pin_card(
        card_entry=_removed_card("abc1230000000001"),
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=registry_path,
        dry_run=False,
    )

    assert result == "archive-existed"
    rows = [json.loads(ln) for ln in registry_path.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["preserved"] is True
    assert rows[0]["byte_sha256"] == _FAKE_PDF_SHA


def test_pin_fails_when_current_pointer_missing_from_r2(tmp_path: Path) -> None:
    """If <card_id>.<ext> isn't in R2, surface the gap — don't write a registry row."""
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    client = MagicMock()
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}},
        "HeadObject",
    )

    registry_path = tmp_path / "registry.jsonl"
    result = r2_pin_removed.pin_card(
        card_entry=_removed_card("0000000000000bad"),
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=registry_path,
        dry_run=False,
    )

    assert result == "missing-in-r2"
    client.get_object.assert_not_called()
    client.put_object.assert_not_called()
    assert not registry_path.exists()


def test_pin_dry_run_makes_no_writes(tmp_path: Path) -> None:
    """Dry-run flips all writes (R2 PUT + registry append) to no-ops."""
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": len(_FAKE_PDF_BYTES)}
    client.get_object.return_value = _fake_get_object(_FAKE_PDF_BYTES)

    registry_path = tmp_path / "registry.jsonl"
    result = r2_pin_removed.pin_card(
        card_entry=_removed_card("abc1230000000001"),
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=registry_path,
        dry_run=True,
    )

    assert result == "would-pin"
    client.put_object.assert_not_called()
    assert not registry_path.exists()


def test_pin_refuses_an_extension_outside_the_map(tmp_path: Path) -> None:
    """A crafted upstream filename is refused, not archived under a guessed key."""
    client = MagicMock()
    registry_path = tmp_path / "registry.jsonl"
    card = _removed_card("abc1230000000001", asset_filename="malicious.../etc/passwd")

    status = r2_pin_removed.pin_card(
        card_entry=card,
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=registry_path,
        dry_run=False,
    )

    assert status == "refused"
    assert client.method_calls == []  # no HEAD, GET or PUT
    assert not registry_path.exists()


@pytest.mark.parametrize("bad_id", ["abc123", "ABC1230000000001", "../etc/passwd0000", "x" * 16])
def test_pin_refuses_a_malformed_card_id_before_any_request(
    tmp_path: Path, bad_id: str
) -> None:
    client = MagicMock()
    status = r2_pin_removed.pin_card(
        card_entry=_removed_card(bad_id),
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=tmp_path / "registry.jsonl",
        dry_run=False,
    )
    assert status == "refused"
    assert client.method_calls == []


def test_pin_takes_the_content_type_from_the_extension_map(tmp_path: Path) -> None:
    client = MagicMock()
    client.head_object.return_value = {"ContentLength": len(_FAKE_PDF_BYTES)}
    client.get_object.return_value = _fake_get_object(_FAKE_PDF_BYTES)
    card = _removed_card("abc1230000000001", asset_filename="photo.JPG")

    r2_pin_removed.pin_card(
        card_entry=card,
        client=client,
        bucket="pursue-pdfs",
        registry={},
        registry_path=tmp_path / "registry.jsonl",
        dry_run=False,
    )

    put_kwargs = client.put_object.call_args.kwargs
    assert put_kwargs["Key"] == f"archive/{_FAKE_PDF_SHA}.jpg"
    assert put_kwargs["ContentType"] == "image/jpeg"


def test_a_put_error_without_a_response_reraises_the_original() -> None:
    class BoomError(Exception):
        response = None

    client = MagicMock()
    client.put_object.side_effect = BoomError("network down")
    with pytest.raises(BoomError, match="network down"):
        r2_pin_removed._put_archive_append_only(
            client, "pursue-pdfs", "archive/x.pdf", b"x", "application/pdf"
        )


def test_main_exits_nonzero_when_a_card_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed = tmp_path / "removed-cards.json"
    removed.write_text(json.dumps({"removed": [
        _removed_card("abc1230000000001", asset_filename="x.exe")]}))
    monkeypatch.setattr(r2_pin_removed, "make_r2_client", MagicMock)
    monkeypatch.setattr(sys, "argv", ["r2_pin_removed.py", "--removed", str(removed),
                                      "--registry", str(tmp_path / "registry.jsonl")])
    assert r2_pin_removed.main() == 1
