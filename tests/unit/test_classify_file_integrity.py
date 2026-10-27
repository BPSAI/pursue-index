"""Worker-side sha re-verification, regular-file-only inputs, and the
cross-check's share of the inflated-bytes budget."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import pytest

from pursue_index import classify_isolated, pdf_limits
from pursue_index.pdf_crosscheck import crosscheck
from pursue_index.pdf_limits import Budget, LimitExceededError
from pursue_index.tranche_bytes import classify_bytes
from pursue_index.tranche_resave import _verified_path
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave, write_pair

CC = "content-changed"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pair(tmp_path: Path):
    base = build_base_pdf()
    return write_pair(tmp_path, base.data, metadata_only_resave(base))


def test_matching_shas_still_classify_in_the_worker(tmp_path) -> None:
    old, new = _pair(tmp_path)
    assert classify_bytes(old, new, old_sha256=_sha(old), new_sha256=_sha(new)) == "metadata-only"


def test_file_swapped_between_parent_check_and_worker_is_content_changed(
    tmp_path, monkeypatch,
) -> None:
    old, new = _pair(tmp_path)
    shas = (_sha(old), _sha(new))
    real = classify_isolated.run_worker

    def swap_then_run(*args, **kwargs):
        new.write_bytes(old.read_bytes())  # different bytes than the parent verified
        return real(*args, **kwargs)

    monkeypatch.setattr("pursue_index.tranche_bytes.run_worker", swap_then_run)
    assert classify_bytes(old, new, old_sha256=shas[0], new_sha256=shas[1]) == CC


def test_in_process_sha_mismatch_is_logged_and_content_changed(tmp_path, caplog) -> None:
    old, new = _pair(tmp_path)
    with caplog.at_level(logging.WARNING):
        verdict = classify_bytes(old, new, isolated=False,
                                 old_sha256=_sha(old), new_sha256="0" * 64)
    assert verdict == CC
    assert "sha mismatch inside worker" in caplog.text


def test_fifo_is_refused_without_blocking(tmp_path) -> None:
    fifo = tmp_path / "f.pdf"
    os.mkfifo(fifo)
    with pytest.raises(LimitExceededError):
        pdf_limits.check_file_size(fifo)
    assert classify_bytes(fifo, fifo) == CC


def test_symlink_is_refused_everywhere(tmp_path) -> None:
    old, new = _pair(tmp_path)
    link = tmp_path / "link.pdf"
    link.symlink_to(new)
    with pytest.raises(LimitExceededError):
        pdf_limits.check_file_size(link)
    with pytest.raises(LimitExceededError):
        pdf_limits.read_capped(link)
    assert classify_bytes(old, link) == CC
    assert classify_bytes(old, link, isolated=False) == CC


def test_verified_path_refuses_a_symlink_or_fifo(tmp_path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"%PDF-1.4 x")
    sha = hashlib.sha256(b"%PDF-1.4 x").hexdigest()
    (tmp_path / f"{sha}.pdf").symlink_to(real)
    assert _verified_path(tmp_path, sha) is None
    other = "cd" * 32
    os.mkfifo(tmp_path / f"{other}.pdf")
    assert _verified_path(tmp_path, other) is None


def test_crosscheck_page_inflation_is_charged_to_the_budget(tmp_path, monkeypatch) -> None:
    old, new = _pair(tmp_path)
    assert crosscheck(old.read_bytes(), new.read_bytes(), Budget())
    monkeypatch.setattr(pdf_limits, "MAX_TOTAL_INFLATED", 1)
    with pytest.raises(LimitExceededError):
        crosscheck(old.read_bytes(), new.read_bytes(), Budget())
