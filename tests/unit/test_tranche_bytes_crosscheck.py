"""A ``metadata-only`` verdict must also pass a cross-check that never uses
``pdf_update``: pypdf's own per-page content-stream hashes and page text.

The hand-rolled parser is stubbed to say ``metadata-only`` for pairs it
should never approve; the cross-check alone must then refuse them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pursue_index import pdf_crosscheck, tranche_bytes
from pursue_index.pdf_limits import Budget
from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import (
    build_base_pdf,
    content_changed_resave,
    metadata_only_resave,
    write_pair,
)

CC = "content-changed"


@pytest.fixture
def parser_lies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tranche_bytes, "_is_metadata_only", lambda *a, **k: True)


def _classify(tmp_path: Path, old: bytes, new: bytes) -> str:
    return classify_bytes(*write_pair(tmp_path, old, new), isolated=False)


def test_content_stream_differs_by_one_byte_is_content_changed(
    tmp_path, caplog, parser_lies,
) -> None:
    base = build_base_pdf()
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, content_changed_resave(base)) == CC
    assert "content-streams" in caplog.text


def test_text_signal_alone_refuses_when_streams_agree(monkeypatch) -> None:
    base = build_base_pdf()
    monkeypatch.setattr(pdf_crosscheck, "_page_digest", lambda page, budget: "same")
    with pytest.raises(pdf_crosscheck.CrossCheckError) as err:
        pdf_crosscheck.crosscheck(base.data, content_changed_resave(base), Budget())
    assert err.value.signal == "text"


@pytest.mark.parametrize("xref_stream", [True, False])
def test_metadata_only_fixtures_pass_both_crosschecks(xref_stream: bool) -> None:
    base = build_base_pdf()
    new = metadata_only_resave(base, xref_stream=xref_stream)
    assert pdf_crosscheck.crosscheck(base.data, new, Budget()) == ("content-streams", "text")


@pytest.mark.parametrize("failing_call", [1, 2])
def test_pypdf_failure_on_either_file_is_content_changed(
    tmp_path, caplog, parser_lies, monkeypatch, failing_call: int,
) -> None:
    base = build_base_pdf()
    real, calls = pdf_crosscheck.PdfReader, []

    def flaky(stream):
        calls.append(1)
        if len(calls) == failing_call:
            raise ValueError("boom")
        return real(stream)

    monkeypatch.setattr(pdf_crosscheck, "PdfReader", flaky)
    with caplog.at_level(logging.WARNING):
        assert _classify(tmp_path, base.data, metadata_only_resave(base)) == CC
    assert "pypdf" in caplog.text


def test_genuine_resave_still_metadata_only_end_to_end(tmp_path) -> None:
    base = build_base_pdf()
    assert _classify(tmp_path, base.data, metadata_only_resave(base)) == "metadata-only"
