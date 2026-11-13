"""Small classifier details: the classifier id covers every source that can
change a verdict, the bytes-dir check opens like the worker does, and the
cross-check's text signal inflates each content stream once."""

from __future__ import annotations

import hashlib
import io
import os
import zlib
from pathlib import Path

import pypdf.filters
import pytest
from pypdf import PdfReader

from pursue_index import classifier_id, pdf_crosscheck, pdf_limits, tranche_resave
from pursue_index.pdf_limits import Budget
from tests.support.tranche_bytes_fakes import append_update, build_base_pdf, stream_body


def test_classifier_id_hashes_the_reference_scan_and_the_worker() -> None:
    names = {p.name for p in classifier_id._SOURCES}
    assert {"pdf_refs.py", "classify_worker.py", "tranche_bytes.py", "pdf_update.py",
            "pdf_limits.py", "pdf_crosscheck.py", "classify_isolated.py"} <= names


def _stage(tmp_path: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / f"{sha}.pdf").write_bytes(data)
    return sha


def test_verified_path_refuses_a_symlink_swapped_in_after_the_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"%PDF-1.4 small"
    sha = hashlib.sha256(data).hexdigest()
    (tmp_path / "real.pdf").write_bytes(data)
    (tmp_path / f"{sha}.pdf").symlink_to(tmp_path / "real.pdf")
    monkeypatch.setattr(pdf_limits, "check_file_size", lambda path: None)  # the race: stat passed
    assert tranche_resave._verified_path(tmp_path, sha) is None


def test_verified_path_refuses_a_fifo_swapped_in_after_the_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "f" * 64
    os.mkfifo(tmp_path / f"{sha}.pdf")
    monkeypatch.setattr(pdf_limits, "check_file_size", lambda path: None)
    assert tranche_resave._verified_path(tmp_path, sha) is None  # returns, never blocks


def test_verified_path_rechecks_the_size_on_the_open_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = _stage(tmp_path, b"x" * 64)
    monkeypatch.setattr(pdf_limits, "check_file_size", lambda path: None)
    monkeypatch.setattr(pdf_limits, "MAX_FILE_BYTES", 10)
    assert tranche_resave._verified_path(tmp_path, sha) is None


def test_verified_path_still_accepts_a_regular_file(tmp_path: Path) -> None:
    sha = _stage(tmp_path, b"%PDF-1.4 small")
    assert tranche_resave._verified_path(tmp_path, sha) == tmp_path / f"{sha}.pdf"


def test_text_signal_inflates_each_content_stream_once(monkeypatch: pytest.MonkeyPatch) -> None:
    base = build_base_pdf()
    reader = PdfReader(io.BytesIO(base.data))
    page_num = reader.pages[0].indirect_reference.idnum
    n = base.size
    page = reader.pages[0].get_object()
    body = (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 200 200] /Contents [%d 0 R %d 0 R] "
            b"/Resources << >> >>" % (page.raw_get("/Parent").idnum, n, n + 1))
    objects = {
        page_num: body,
        n: stream_body(zlib.compress(b"BT /F1 9 Tf (A) Tj ET"), b"/Filter /FlateDecode"),
        n + 1: stream_body(zlib.compress(b"BT /F1 9 Tf (B) Tj ET"), b"/Filter /FlateDecode"),
    }
    data = append_update(base.data, objects, root=base.root_num, info=base.info_num, size=n + 2)
    calls: list[int] = []
    real = pypdf.filters.decode_stream_data

    def counting(stream):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real(stream)

    monkeypatch.setattr(pypdf.filters, "decode_stream_data", counting)
    budget = Budget()
    pdf_crosscheck._page_text(PdfReader(io.BytesIO(data)).pages[0], budget)
    assert len(calls) == 2
