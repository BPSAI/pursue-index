"""Verify-gates round 3: a full disk reports what was measured, and no failure leaves a partial file."""

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

from tests.unit.test_r2_disk_head_review import _full_after  # noqa: E402
from tests.unit.test_r2_fetch_bounds import HOSTS, URL, _Resp, _serve  # noqa: E402

pytestmark = pytest.mark.usefixtures("dns")

Usage = namedtuple("Usage", "total used free")
GB = 10**9


def _free_sequence(monkeypatch, first: int, then: int) -> None:
    calls: list[int] = []

    def usage(_p):
        calls.append(1)
        return Usage(10**13, 0, first if len(calls) == 1 else then)

    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", usage)


def test_enospc_mid_stream_reports_the_measured_need_and_free(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _free_sequence(monkeypatch, first=10 * GB, then=12345)
    _full_after(monkeypatch, dest, ok=1)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 10, b"y" * 10, b"z" * 10])})
    with pytest.raises(_r2_fetch.InsufficientDiskError) as exc:
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS, known_size=1000)
    assert exc.value.free == 12345
    assert exc.value.need == 2000 + _r2_fetch.DISK_MARGIN_BYTES  # expected size plus margin
    assert not dest.exists()


def test_enospc_reports_the_bytes_already_written_when_they_pass_the_expectation(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _free_sequence(monkeypatch, first=10 * GB, then=7)
    _full_after(monkeypatch, dest, ok=3)
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 100, b"y" * 100, b"z" * 100, b"w" * 100])})
    with pytest.raises(_r2_fetch.InsufficientDiskError) as exc:
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS, known_size=10)
    assert exc.value.free == 7
    assert exc.value.need == 300 + _r2_fetch.DISK_MARGIN_BYTES
    assert not dest.exists()


class _Boom(_Resp):
    def iter_content(self, chunk_size: int = 0):
        yield b"x" * 10
        raise RuntimeError("connection reset")


class _Stall(_Resp):
    def iter_content(self, chunk_size: int = 0):
        yield b"x" * 10
        yield b"y" * 10


def test_a_generic_stream_error_leaves_no_partial_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _serve(monkeypatch, {URL: _Boom()})
    with pytest.raises(RuntimeError):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS)
    assert not dest.exists()


def test_growth_past_the_cap_mid_stream_leaves_no_partial_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x" * 10, b"y" * 10, b"z" * 10])})
    with pytest.raises(_r2_fetch.FetchOverCapError):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=15, allowed_hosts=HOSTS)
    assert not dest.exists()


def test_an_idle_timeout_mid_stream_leaves_no_partial_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    clock = iter([0.0, 1.0, 1.0 + _r2_fetch.IDLE_TIMEOUT_S + 1, 99999.0])
    monkeypatch.setattr(_r2_fetch, "_now", lambda: next(clock))
    _serve(monkeypatch, {URL: _Stall()})
    with pytest.raises(_r2_fetch.FetchTimeoutError):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS)
    assert not dest.exists()


def test_a_free_space_failure_before_the_stream_leaves_no_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    monkeypatch.setattr(_r2_fetch.shutil, "disk_usage", lambda _p: Usage(10**13, 0, 0))
    _serve(monkeypatch, {URL: _Resp(chunks=[b"x"])})
    with pytest.raises(_r2_fetch.InsufficientDiskError):
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10**6, allowed_hosts=HOSTS)
    assert not dest.exists()


def test_a_declared_length_over_the_disk_leaves_no_file(monkeypatch, tmp_path):
    dest = tmp_path / "a"
    _free_sequence(monkeypatch, first=10 * GB, then=5)
    _serve(monkeypatch, {URL: _Resp(headers={"content-length": str(5 * GB)}, chunks=[b"x"])})
    with pytest.raises(_r2_fetch.InsufficientDiskError) as exc:
        _r2_fetch.fetch_asset(URL, dest, max_bytes=10 * GB, allowed_hosts=HOSTS)
    assert exc.value.free == 5 and exc.value.need == 5 * GB + _r2_fetch.DISK_MARGIN_BYTES
    assert not dest.exists()
