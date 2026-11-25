"""Review round 2: disk headroom follows the expected size, and HEAD keeps encoded responses usable."""

from __future__ import annotations

import errno
import sys
from collections import namedtuple
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_fetch  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2  # noqa: E402
from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _Resp, _serve  # noqa: E402

pytestmark = pytest.mark.usefixtures("dns")

MIB = 1024**2
GB = 10**9
Usage = namedtuple("Usage", "total used free")
KNOWN_VIDEO = 3_212_900_000


def _free(monkeypatch, free: int) -> None:
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**13, 0, free))


# --- disk headroom: expected size, not the hard ceiling -------------------------------------


def test_a_large_known_asset_passes_the_precheck_on_a_14_gb_runner(monkeypatch, tmp_path):
    _free(monkeypatch, 14 * GB)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    ceiling = _r2_fetch.hard_ceiling([{"byte_size": KNOWN_VIDEO}])
    assert ceiling > 14 * GB, "the hard ceiling alone would never fit"
    got = _r2_fetch.fetch_asset(
        URL, tmp_path / "a", max_bytes=ceiling, allowed_hosts=HOSTS, known_size=KNOWN_VIDEO
    )
    assert got[1] == 1


def test_a_declared_size_over_the_free_space_is_refused_before_any_byte(monkeypatch, tmp_path):
    _free(monkeypatch, 8 * GB)
    resp = _Resp(headers={"content-length": str(9 * GB)}, chunks=[b"x"])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.InsufficientDiskError, match="insufficient disk"):
        _r2_fetch.fetch_asset(
            URL, tmp_path / "a", max_bytes=30 * GB, allowed_hosts=HOSTS, known_size=KNOWN_VIDEO
        )
    assert resp.yielded == 0 and resp.closed
    assert not (tmp_path / "a").exists()


def test_a_declared_size_that_fits_with_the_margin_passes(monkeypatch, tmp_path):
    _free(monkeypatch, 3 * GB)
    _serve(monkeypatch, {URL: _Resp(headers={"content-length": "1"}, chunks=[b"x"])})
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=30 * GB, allowed_hosts=HOSTS)[1] == 1


def test_an_unknown_size_expects_512_mib_plus_the_margin(monkeypatch, tmp_path):
    need = 512 * MIB + _r2_fetch.DISK_MARGIN_BYTES
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _free(monkeypatch, need)
    assert _r2_fetch.fetch_asset(URL, tmp_path / "a", max_bytes=30 * GB, allowed_hosts=HOSTS)[1] == 1
    _free(monkeypatch, need - 1)
    with pytest.raises(_r2_fetch.InsufficientDiskError):
        _r2_fetch.fetch_asset(URL, tmp_path / "b", max_bytes=30 * GB, allowed_hosts=HOSTS)


def test_a_known_size_expects_twice_that_plus_the_margin(monkeypatch, tmp_path):
    need = 2 * 100 * MIB + _r2_fetch.DISK_MARGIN_BYTES
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    _free(monkeypatch, need - 1)
    with pytest.raises(_r2_fetch.InsufficientDiskError):
        _r2_fetch.fetch_asset(
            URL, tmp_path / "a", max_bytes=30 * GB, allowed_hosts=HOSTS, known_size=100 * MIB
        )
    _free(monkeypatch, need)
    assert _r2_fetch.fetch_asset(
        URL, tmp_path / "b", max_bytes=30 * GB, allowed_hosts=HOSTS, known_size=100 * MIB
    )[1] == 1


class _FullDisk:
    """A file object that takes ``ok`` writes, then fails like a full disk."""

    def __init__(self, real, ok: int) -> None:
        self._real, self._ok = real, ok

    def write(self, data):
        if self._ok <= 0:
            raise OSError(errno.ENOSPC, "No space left on device")
        self._ok -= 1
        return self._real.write(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._real.close()
        return False


def _full_after(monkeypatch, dest: Path, ok: int) -> None:
    real_open = Path.open

    def fake_open(self, *a, **k):
        fh = real_open(self, *a, **k)
        return _FullDisk(fh, ok) if self == dest else fh

    monkeypatch.setattr(Path, "open", fake_open)


def test_enospc_mid_stream_is_an_insufficient_disk_failure_with_no_partial_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _full_after(monkeypatch, dest, ok=1)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 10, b"y" * 10, b"z" * 10])})
    with pytest.raises(_r2_fetch.InsufficientDiskError, match="insufficient disk"):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS)
    assert not dest.exists()


def test_free_space_falling_under_the_margin_mid_stream_aborts_and_removes_the_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    monkeypatch.setattr(_r2_fetch, "DISK_CHECK_EVERY_BYTES", 1)
    frees = iter([10 * GB, 10 * GB, _r2_fetch.DISK_MARGIN_BYTES - 1])
    monkeypatch.setattr(
        _r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**13, 0, next(frees, 0))
    )
    resp = _Resp(chunks=[b"x" * 10, b"y" * 10, b"z" * 10, b"w" * 10])
    _serve(monkeypatch, {URL: resp})
    with pytest.raises(_r2_fetch.InsufficientDiskError):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS)
    assert not dest.exists() and resp.yielded < 4


def test_a_full_disk_fails_that_card_and_the_next_card_still_runs(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    bad = w.add_card(1, body=NEW_BODY)
    ok = w.add_card(2, body=NEW_BODY)

    def fetch(u, dest, **kw):
        if "c1." in str(u):
            Path(dest).write_bytes(b"partial")
            raise _r2_fetch.InsufficientDiskError(need=5, free=0)
        Path(dest).write_bytes(NEW_BODY)
        return __import__("hashlib").sha256(NEW_BODY).hexdigest(), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    w.run()
    out = capsys.readouterr().out
    assert f"fetch fail {bad}" in out and "insufficient disk" in out and "fail=1" in out
    assert [r["card_id"] for r in w.new_rows()] == [ok]


def test_the_archive_passes_each_cards_last_known_size_to_the_fetch(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    seen: dict = {}

    def fetch(u, dest, **kw):
        seen.update(kw)
        Path(dest).write_bytes(NEW_BODY)
        return __import__("hashlib").sha256(NEW_BODY).hexdigest(), len(NEW_BODY)

    monkeypatch.setattr(r2, "fetch_asset", fetch)
    assert w.run() == 0
    assert seen["known_size"] == len(OLD_BODY)


# --- HEAD on an encoded response ---------------------------------------------------------------

ENC = {"content-length": "7", "content-encoding": "gzip", "etag": '"e1"'}


def _rows(**kw):
    return [{"byte_size": 5000, "upstream_etag": '"e1"', "upstream_last_modified": None, **kw}]


def test_head_flags_an_encoded_response_and_still_reports_no_size(monkeypatch):
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: _Resp(headers=ENC))
    got = _r2_fetch.head_asset(URL, allowed_hosts=HOSTS)
    assert got == (None, '"e1"', None) and got.encoded is True


def test_head_does_not_flag_a_plain_response(monkeypatch):
    plain = {"content-length": "7", "etag": '"e1"'}
    monkeypatch.setattr(_r2_fetch.cffi_requests, "head", lambda u, **k: _Resp(headers=plain))
    got = _r2_fetch.head_asset(URL, allowed_hosts=HOSTS)
    assert got == (7, '"e1"', None) and got.encoded is False


def test_an_encoded_response_with_a_matching_etag_is_identical_without_a_size():
    assert _r2_fetch.head_identical(_rows(), None, '"e1"', None, encoded=True)


def test_an_encoded_response_with_a_different_etag_is_not_identical():
    assert not _r2_fetch.head_identical(_rows(), None, '"e2"', None, encoded=True)


def test_an_encoded_response_falls_back_to_last_modified_without_etags():
    lm = "Wed, 01 Jul 2026 00:00:00 GMT"
    rows = _rows(upstream_etag=None, upstream_last_modified=lm)
    assert _r2_fetch.head_identical(rows, None, None, lm, encoded=True)
    assert not _r2_fetch.head_identical(rows, None, None, None, encoded=True)
    assert not _r2_fetch.head_identical(rows, None, None, "Thu, 02 Jul 2026 00:00:00 GMT", encoded=True)


def test_a_missing_size_on_a_plain_response_still_forces_a_fetch():
    assert not _r2_fetch.head_identical(_rows(), None, '"e1"', None)


def test_an_encoded_unchanged_asset_is_not_refetched_on_the_daily_poll(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    monkeypatch.setattr(
        r2, "head_asset", lambda u, hosts=None: _r2_fetch.HeadResult((None, '"e1"', None), encoded=True)
    )
    assert w.run() == 0
    assert w.fetched == []
    assert "head-unchanged (unverified)=1" in capsys.readouterr().out
