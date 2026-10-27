"""Resource caps on ``classify_bytes``: a crafted PDF must fail safe, cheaply.

Every cap hit classifies ``content-changed`` (the fail-safe class: the row
stays quarantined for an operator), never ``metadata-only``, and logs why.
"""

from __future__ import annotations

import logging
import time
import tracemalloc
import zlib
from pathlib import Path

import pytest

from pursue_index import pdf_limits, tranche_bytes
from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import (
    BasePdf,
    build_base_pdf,
    info_body,
    last_startxref,
    metadata_only_resave,
    write_pair,
)

CC = "content-changed"


def _xref_stream_update(base: BasePdf, *, index: bytes, payload: bytes,
                        flate: bool = False) -> bytes:
    """``base`` plus an info object and a hand-built xref stream ``/Index``."""
    out = bytearray(base.data if base.data.endswith(b"\n") else base.data + b"\n")
    out += b"%d 0 obj\n" % base.size + info_body() + b"\nendobj\n"
    at, num = len(out), base.size + 1
    filt = b" /Filter /FlateDecode" if flate else b""
    head = (b"<< /Type /XRef /W [1 4 2] /Index [" + index + b"] /Size %d /Root %d 0 R"
            b" /Info %d 0 R /Prev %d%s /Length %d >>\nstream\n"
            % (num + 1, base.root_num, base.size, last_startxref(base.data), filt, len(payload)))
    out += b"%d 0 obj\n" % num + head + payload + b"\nendstream\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF\n" % at
    return bytes(out)


def _classify(tmp_path: Path, old: bytes, new: bytes) -> str:
    return classify_bytes(*write_pair(tmp_path, old, new), isolated=False)


def test_huge_index_count_fails_safe_without_allocating(tmp_path, caplog) -> None:
    base = build_base_pdf()
    new = _xref_stream_update(base, index=b"0 999999999", payload=b"\x01" * 7)
    tracemalloc.start()
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        verdict = _classify(tmp_path, base.data, new)
    elapsed, (_, peak) = time.monotonic() - started, tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert verdict == CC
    assert elapsed < 1.0 and peak < 16 * 1024 * 1024
    assert "xref-entry-ceiling" in caplog.text


def test_decompression_bomb_aborts_at_the_cap(tmp_path, caplog) -> None:
    base = build_base_pdf()
    bomb = zlib.compress(b"\x00" * (pdf_limits.MAX_XREF_INFLATED + 1024 * 1024))
    assert len(bomb) < 64 * 1024
    new = _xref_stream_update(base, index=b"0 1", payload=bomb, flate=True)
    tracemalloc.start()
    with caplog.at_level(logging.WARNING):
        verdict = _classify(tmp_path, base.data, new)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert verdict == CC
    assert peak < 3 * pdf_limits.MAX_XREF_INFLATED
    assert "xref-inflate-cap" in caplog.text


def test_update_count_cap_is_a_logged_fail_safe(tmp_path, caplog, monkeypatch) -> None:
    base = build_base_pdf()
    once = metadata_only_resave(base, xref_stream=False)
    monkeypatch.setattr(pdf_limits, "MAX_UPDATES", 1)
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, once) == CC
    assert "update-count" in caplog.text


def test_time_budget_hit_never_yields_metadata_only(tmp_path, caplog, monkeypatch) -> None:
    base = build_base_pdf()
    good = metadata_only_resave(base)
    assert _classify(tmp_path, base.data, good) == "metadata-only"
    monkeypatch.setattr(pdf_limits, "TIME_BUDGET_SECONDS", 0.0)
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, good) == CC
    assert "time-budget" in caplog.text


def test_total_bytes_budget_hit_never_yields_metadata_only(tmp_path, caplog, monkeypatch) -> None:
    base = build_base_pdf()
    good = metadata_only_resave(base)
    monkeypatch.setattr(pdf_limits, "MAX_TOTAL_INFLATED", 4)
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, good) == CC
    assert "total-bytes-budget" in caplog.text


def test_over_cap_file_is_refused_before_it_is_read(tmp_path, caplog, monkeypatch) -> None:
    base = build_base_pdf()
    old, new = write_pair(tmp_path, base.data, metadata_only_resave(base))

    def boom(self):
        raise AssertionError("read_bytes called on an over-cap file")

    monkeypatch.setattr(pdf_limits, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(Path, "read_bytes", boom)
    with caplog.at_level(logging.WARNING):
        assert classify_bytes(old, new, isolated=False) == CC
    assert "file-size-cap" in caplog.text


def test_in_cap_pair_still_classifies_metadata_only(tmp_path) -> None:
    base = build_base_pdf()
    assert _classify(tmp_path, base.data, metadata_only_resave(base)) == "metadata-only"
    assert tranche_bytes.METADATA_ONLY == "metadata-only"
    with pytest.raises(FileNotFoundError):
        classify_bytes(tmp_path / "missing.pdf", tmp_path / "new.pdf")


def test_update_count_bounds_the_old_chain_via_the_full_prefix(tmp_path, caplog, monkeypatch) -> None:
    """``new`` carries ``old`` as its prefix, so counting ``new`` counts the
    ``/Prev`` chain pypdf walks through the old file too."""
    base = build_base_pdf()
    once = metadata_only_resave(base, xref_stream=False)
    assert pdf_limits.check_update_count(once) == once.count(b"startxref") >= 2
    monkeypatch.setattr(pdf_limits, "MAX_UPDATES", base.data.count(b"startxref"))
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, once) == CC
    assert "update-count" in caplog.text


def test_suffix_alone_is_rejected(tmp_path) -> None:
    base = build_base_pdf()
    once = metadata_only_resave(base, xref_stream=False)
    assert _classify(tmp_path, base.data, once[len(base.data):]) == CC
