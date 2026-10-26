"""``classify_bytes`` runs in a resource-limited worker; any worker failure
(crash, memory ceiling, hang, garbage output) is ``content-changed``."""

from __future__ import annotations

import logging
import sys
import textwrap
import time
from pathlib import Path

import pytest

from pursue_index import classify_isolated, pdf_limits
from pursue_index.tranche_bytes import classify_bytes
from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave, write_pair

CC = "content-changed"


@pytest.fixture
def stub_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def install(body: str) -> None:
        (tmp_path / "p3stub_worker.py").write_text(textwrap.dedent(body))
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(classify_isolated, "WORKER_MODULE", "p3stub_worker")
    return install


def _pair(tmp_path: Path):
    base = build_base_pdf()
    return write_pair(tmp_path, base.data, metadata_only_resave(base))


def test_default_path_uses_the_worker_and_still_classifies(tmp_path) -> None:
    assert classify_bytes(*_pair(tmp_path)) == "metadata-only"


def test_hanging_worker_is_content_changed_within_the_timeout(
    tmp_path, stub_worker, monkeypatch, caplog,
) -> None:
    stub_worker("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(pdf_limits, "TIME_BUDGET_SECONDS", 1.0)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        assert classify_bytes(*_pair(tmp_path)) == CC
    assert time.monotonic() - started < 5
    assert "worker-timeout" in caplog.text


def test_worker_over_the_memory_ceiling_is_content_changed(
    tmp_path, stub_worker, monkeypatch, caplog,
) -> None:
    stub_worker("""
        import sys
        from pursue_index.classify_worker import apply_memory_limit
        apply_memory_limit(int(sys.argv[sys.argv.index("--memory-bytes") + 1]))
        hog = bytearray(900 * 1024 * 1024)
        print("metadata-only")
    """)
    monkeypatch.setattr(classify_isolated, "WORKER_MEMORY_BYTES", 400 * 1024 * 1024)
    with caplog.at_level(logging.WARNING):
        assert classify_bytes(*_pair(tmp_path)) == CC
    assert "worker-failed" in caplog.text


@pytest.mark.parametrize("body", ["import sys\nsys.exit(3)\n",
                                  "print('metadata-only maybe')\n",
                                  "print('metadata-only')\nimport sys\nsys.exit(1)\n"])
def test_crash_garbage_or_nonzero_exit_is_content_changed(tmp_path, stub_worker, body) -> None:
    stub_worker(body)
    assert classify_bytes(*_pair(tmp_path)) == CC


def test_missing_file_still_raises_before_a_worker_is_spawned(tmp_path) -> None:
    old, _ = _pair(tmp_path)
    with pytest.raises(FileNotFoundError):
        classify_bytes(old, tmp_path / "absent.pdf")
    assert sys.executable
