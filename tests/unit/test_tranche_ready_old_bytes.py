"""``pursue_index.tranche_ready.old_bytes`` -- staging both sides' bytes.

The old side is fetched credential-free from the URL the site already
serves for the old card, through the same Chrome-impersonated, allowlisted,
size-capped client the page counter uses (``pdf_pages.fetch_pdf``), and is
trusted only when it hashes to the old card's registry sha. A trusted file
lands in the content-addressed bytes dir as ``<sha256>.pdf`` (the
``--bytes-dir`` convention ``tranche_resave`` reads); an untrusted one never
does. The new side is the page counter's already-fetched file, copied in
under its own sha -- never fetched twice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher
from pursue_index.tranche_ready.old_bytes import stage_new, stage_old
from tests.support.pdf_page_fakes import FakeHttpGet

_URL = "https://www.war.gov/medialink/ufo/release_1/old.pdf"
_BODY = b"%PDF-1.4 old bytes"
_SHA = hashlib.sha256(_BODY).hexdigest()


@pytest.fixture
def bytes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bytes"
    d.mkdir()
    return d


def test_old_bytes_matching_the_registry_land_under_their_sha(
    bytes_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_URL: _BODY}))
    staged = stage_old(_URL, _SHA, bytes_dir)
    assert staged.failure is None
    assert staged.path == bytes_dir / f"{_SHA}.pdf"
    assert staged.path.read_bytes() == _BODY
    assert (staged.sha256, staged.size) == (_SHA, len(_BODY))


def test_old_bytes_that_disagree_with_the_registry_are_never_staged(bytes_dir: Path) -> None:
    staged = stage_old(_URL, "0" * 64, bytes_dir, fetch=lambda url: _BODY)
    assert staged.failure == "old_sha_mismatch"
    assert staged.path is None
    assert staged.sha256 == _SHA  # the evidence: what the URL actually served
    assert list(bytes_dir.iterdir()) == []


def test_an_unreachable_or_disallowed_old_url_is_an_old_fetch_failure(bytes_dir: Path) -> None:
    def boom(url: str) -> bytes:
        raise OSError("HTTP 404")

    assert stage_old(_URL, _SHA, bytes_dir, fetch=boom).failure == "old_fetch_failed"
    called: list[str] = []
    disallowed = stage_old("http://evil.example/x.pdf", _SHA, bytes_dir, fetch=called.append)
    assert disallowed.failure == "old_fetch_failed" and called == []
    assert stage_old(None, _SHA, bytes_dir).failure == "old_fetch_failed"
    assert list(bytes_dir.iterdir()) == []


def test_no_registry_sha_means_the_old_bytes_cannot_be_trusted(bytes_dir: Path) -> None:
    staged = stage_old(_URL, None, bytes_dir, fetch=lambda url: _BODY)
    assert staged.failure == "old_sha_mismatch" and staged.path is None


def test_new_bytes_are_copied_from_the_page_counters_file(tmp_path: Path, bytes_dir: Path) -> None:
    fetched = tmp_path / "ff3939f95d878062.pdf"
    fetched.write_bytes(_BODY)
    staged = stage_new(fetched, bytes_dir)
    assert staged.failure is None and staged.path == bytes_dir / f"{_SHA}.pdf"
    assert staged.path.read_bytes() == _BODY
    assert stage_new(None, bytes_dir).failure == "new_fetch_failed"
