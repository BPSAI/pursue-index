"""The worker's search path and cwd are not attacker-reachable, and relative
inputs survive the cwd change."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pursue_index import classify_isolated
from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave, write_pair


def test_a_module_planted_in_the_shared_temp_dir_is_never_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = tmp_path / "shared-tmp"
    shared.mkdir()
    (shared / "colorsys.py").write_text("raise RuntimeError('hijacked')\n")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "p3cwd_worker.py").write_text(textwrap.dedent("""
        import colorsys
        print("metadata-only")
    """))
    monkeypatch.syspath_prepend(str(stubs))
    monkeypatch.setattr(classify_isolated, "WORKER_MODULE", "p3cwd_worker")
    monkeypatch.setattr(classify_isolated.tempfile, "gettempdir", lambda: str(shared))
    assert classify_isolated.run_worker(tmp_path / "a.pdf", tmp_path / "b.pdf") == "metadata-only"


def test_relative_paths_are_classified_not_failed_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = build_base_pdf()
    write_pair(tmp_path, base.data, metadata_only_resave(base))
    monkeypatch.chdir(tmp_path)
    assert classify_bytes(Path("old.pdf"), Path("new.pdf")) == "metadata-only"
