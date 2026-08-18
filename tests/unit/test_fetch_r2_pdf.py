"""Defense-in-depth tests for ``fetch_r2_pdf`` archive_key validation.

The function consumes ``archive_key`` from byte-history.json and forwards
straight into boto3 ``get_object``. The data is currently trustworthy
(operator-controlled JSON), but the registry layer doesn't enforce the
shape on the python side at the call boundary. Validate at the app
layer so a corrupted entry surfaces as a typed error here instead of
a confusing boto3 NoSuchKey on a malformed key.

Format pinned: ``archive/<lowercase-64-hex-sha>.pdf``. Mirrors the
worker's ``BYTE_SHA_RE`` (``worker/pdf.js::BYTE_SHA_RE``) and the
``.pdf``-only contract of ``fetch_r2_pdf``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _reocr_helpers import fetch_r2_pdf  # noqa: E402


def _fake_r2_client(payload: bytes = b"%PDF-1.4\n...") -> MagicMock:
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda: payload)}
    return client


def test_fetch_r2_pdf_accepts_valid_archive_key() -> None:
    client = _fake_r2_client()
    key = "archive/" + "a" * 64 + ".pdf"
    result = fetch_r2_pdf(client, key)
    assert result == b"%PDF-1.4\n..."
    client.get_object.assert_called_once_with(Bucket="pursue-pdfs", Key=key)


@pytest.mark.parametrize("bad_key", [
    # wrong prefix
    "pdf/" + "a" * 64 + ".pdf",
    "/" + "archive/" + "a" * 64 + ".pdf",
    # wrong extension
    "archive/" + "a" * 64 + ".png",
    "archive/" + "a" * 64 + ".mp4",
    "archive/" + "a" * 64 + ".PDF",  # uppercase ext rejected
    # wrong sha length
    "archive/" + "a" * 63 + ".pdf",
    "archive/" + "a" * 65 + ".pdf",
    # non-hex sha
    "archive/" + "g" * 64 + ".pdf",
    # uppercase sha rejected (worker uses lowercase canonical form)
    "archive/" + "A" * 64 + ".pdf",
    # path traversal
    "archive/../etc/passwd",
    "archive/../" + "a" * 64 + ".pdf",
    # empty / nonsense
    "",
    "archive/",
    "archive/.pdf",
])
def test_fetch_r2_pdf_rejects_malformed_archive_key(bad_key: str) -> None:
    """Validation runs BEFORE boto3 — operator gets a typed error, not a
    NoSuchKey from R2."""
    client = _fake_r2_client()
    with pytest.raises(ValueError, match="archive_key"):
        fetch_r2_pdf(client, bad_key)
    # boto3 must not have been called.
    client.get_object.assert_not_called()
