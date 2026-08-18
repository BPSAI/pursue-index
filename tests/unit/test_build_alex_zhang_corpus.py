"""Test the alex-zhang42 corpus build script's revision pinning.

The script (``scripts/build_alex_zhang_corpus.py``) is operator-only — it
needs ``huggingface_hub`` + ``pyarrow`` which are not core deps. The
tests below import the module via ``importlib`` so they can run on a
core install: only the constants and the ``main()`` flow are exercised.

Per SEC-003, the script must hardcode the pinned HF revision
and refuse to silently ingest a different upstream HEAD.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_alex_zhang_corpus.py"


def _stub_hf_modules(
    monkeypatch: pytest.MonkeyPatch, head_sha: str
) -> dict[str, object]:
    """Install fake ``huggingface_hub`` + ``pyarrow.parquet`` modules.

    Returns a dict of call counters so the test can assert what the
    script actually invoked.
    """
    calls: dict[str, object] = {"download_called": False, "head_sha": head_sha}

    class _FakeApi:
        def dataset_info(self, repo_id: str) -> object:
            ns = types.SimpleNamespace(sha=head_sha)
            return ns

    def _fake_hub_download(**kwargs: object) -> str:
        calls["download_called"] = True
        calls["download_kwargs"] = kwargs
        return "/nonexistent/parquet"

    hf_mod = types.ModuleType("huggingface_hub")
    hf_mod.HfApi = _FakeApi
    hf_mod.hf_hub_download = _fake_hub_download

    class _FakeTable:
        num_rows = 0

        def to_pylist(self) -> list[dict]:
            return []

    pq_mod = types.ModuleType("pyarrow.parquet")
    pq_mod.read_table = lambda _path: _FakeTable()
    pa_mod = types.ModuleType("pyarrow")
    pa_mod.parquet = pq_mod

    monkeypatch.setitem(sys.modules, "huggingface_hub", hf_mod)
    monkeypatch.setitem(sys.modules, "pyarrow", pa_mod)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", pq_mod)
    return calls


def _load_script_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_alex_zhang_corpus", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_declares_pinned_revision_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``PINNED_REVISION`` constant must exist and match the committed
    ``data/external/alex-zhang42-corpus.revision`` sidecar.

    Per SEC-003: the revision lives in code, not just in a
    sidecar that a re-run could silently overwrite.
    """
    _stub_hf_modules(monkeypatch, head_sha="anything")
    mod = _load_script_module()
    assert hasattr(mod, "PINNED_REVISION")
    sidecar = REPO_ROOT / "data" / "external" / "alex-zhang42-corpus.revision"
    expected = sidecar.read_text().strip()
    assert mod.PINNED_REVISION == expected


def test_script_aborts_when_upstream_head_drifts_from_pinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If HF HEAD != ``PINNED_REVISION``, refuse to download and write.

    A silent drift would replace the committed JSONL + sha256 with a
    different upstream snapshot. Operator must consciously bump the
    pinned constant before re-running.
    """
    calls = _stub_hf_modules(monkeypatch, head_sha="0" * 40)
    monkeypatch.chdir(tmp_path)
    mod = _load_script_module()
    with pytest.raises(RuntimeError, match="PINNED_REVISION"):
        mod.main()
    assert calls["download_called"] is False


def test_script_runs_when_upstream_head_matches_pinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When HEAD matches, the script proceeds (download is invoked)."""
    mod_path = SCRIPT
    spec = importlib.util.spec_from_file_location(
        "build_alex_zhang_corpus_match", mod_path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Stub before exec so module-level imports of huggingface_hub succeed.
    sidecar = REPO_ROOT / "data" / "external" / "alex-zhang42-corpus.revision"
    pinned = sidecar.read_text().strip()
    calls = _stub_hf_modules(monkeypatch, head_sha=pinned)
    monkeypatch.chdir(tmp_path)
    spec.loader.exec_module(mod)
    mod.main()
    assert calls["download_called"] is True
    assert calls["download_kwargs"]["revision"] == pinned
