"""Characterization tests for the R2 archive PUT step."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _r2_archive_put import put_archive_and_current


class _Client:
    def __init__(self, archive_error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.archive_error = archive_error

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.archive_error is not None and "IfNoneMatch" in kwargs:
            raise self.archive_error


class _PreconditionError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


def _put(client: _Client) -> bool:
    return put_archive_and_current(client, "b", "archive/x.pdf", "c.pdf", b"x", "application/pdf")


def test_new_bytes_write_archive_then_current():
    client = _Client()
    assert _put(client) is False
    assert [c["Key"] for c in client.calls] == ["archive/x.pdf", "c.pdf"]
    assert client.calls[0]["IfNoneMatch"] == "*"
    assert "IfNoneMatch" not in client.calls[1]


def test_existing_archive_key_is_a_hit_and_current_still_updated():
    client = _Client(_PreconditionError("PreconditionFailed"))
    assert _put(client) is True
    assert client.calls[-1]["Key"] == "c.pdf"


def test_other_errors_propagate_and_current_is_not_written():
    client = _Client(_PreconditionError("AccessDenied"))
    with pytest.raises(_PreconditionError):
        _put(client)
    assert [c["Key"] for c in client.calls] == ["archive/x.pdf"]
