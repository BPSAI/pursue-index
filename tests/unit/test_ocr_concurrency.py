"""Tests for OCR pipeline concurrency selection.

``_concurrency_for`` answers "how many pages may be in flight" per engine, and
the answer differs by what the engine is bound on:

- LLM-backed engines (``llm``, ``llm-dots``, ``auto``) parallelize against the
  API and default to the operated value, with ``PURSUE_OCR_LLM_CONCURRENCY``
  overriding it.
- ``surya`` and ``dots`` stay at 1: a single GPU worker with one channel cannot
  truly run concurrent calls, so the LLM setting must not reach them.
- ``tesseract`` is CPU-bound and stays within a small cap of the host's CPUs.

``ocr_all`` layers an explicit ``concurrency`` argument over all of that, wired
to ``pursue ocr run --concurrency``: when given it decides, and when omitted
``_concurrency_for`` does.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from typer.testing import CliRunner

from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.scrape.types import Manifest

_OPERATED_LLM_CONCURRENCY = 8


def _empty_manifest() -> Manifest:
    return Manifest(
        source_url="https://example.com/x.csv",
        fetched_at="2026-05-22T00:00:00Z",
        csv_sha256="0" * 64,
        cards=[],
    )


def _capture_semaphore_size(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the size every ``asyncio.Semaphore`` is constructed with."""
    captured: list[int] = []
    real_semaphore = asyncio.Semaphore

    def _capture(value: int) -> asyncio.Semaphore:
        captured.append(value)
        return real_semaphore(value)

    monkeypatch.setattr(ocr_pipeline.asyncio, "Semaphore", _capture)
    return captured


# ---------------------------------------------------------------------------
# Engine-aware defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["llm", "llm-dots", "auto"])
def test_llm_backed_engines_default_to_the_operated_concurrency(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no env override, every LLM-backed engine uses the operated value."""
    monkeypatch.delenv("PURSUE_OCR_LLM_CONCURRENCY", raising=False)
    assert ocr_pipeline._concurrency_for(engine) == _OPERATED_LLM_CONCURRENCY


def test_env_var_overrides_the_llm_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PURSUE_OCR_LLM_CONCURRENCY`` wins over the default."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "16")
    assert ocr_pipeline._concurrency_for("llm-dots") == 16


@pytest.mark.parametrize("engine", ["surya", "dots"])
def test_single_gpu_engines_stay_serial(
    engine: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One GPU worker on one channel runs one page at a time, whatever the env says."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "16")
    assert ocr_pipeline._concurrency_for(engine) == 1


def test_tesseract_stays_within_the_cpu_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tesseract is CPU-bound: a small cap, never the LLM setting."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "16")
    value = ocr_pipeline._concurrency_for("tesseract")
    assert 1 <= value <= 4
    assert value <= (os.cpu_count() or 1)


# ---------------------------------------------------------------------------
# The explicit override on ocr_all
# ---------------------------------------------------------------------------


def test_ocr_all_uses_the_explicit_concurrency_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr_all(concurrency=N)`` bounds the run at N, above env and engine default."""
    captured = _capture_semaphore_size(monkeypatch)
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "4")

    asyncio.run(ocr_pipeline.ocr_all(_empty_manifest(), engine="llm", concurrency=7))

    assert captured == [7], (
        f"the run should be bounded by the explicit override 7, got {captured}"
    )


def test_ocr_all_falls_back_to_the_engine_default_without_an_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr_all()`` with no ``concurrency`` defers to ``_concurrency_for``."""
    captured = _capture_semaphore_size(monkeypatch)
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "3")

    asyncio.run(ocr_pipeline.ocr_all(_empty_manifest(), engine="llm"))

    assert captured == [3], (
        f"the run should fall back to the engine default 3, got {captured}"
    )


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_passes_concurrency_through_to_the_pipeline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pursue ocr run --concurrency N`` reaches ``ocr_all`` as N."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(_empty_manifest().model_dump_json(by_alias=True))

    captured: dict[str, object] = {}

    async def _fake_ocr_all(manifest, engine=None, force=False, concurrency=None):
        captured["engine"] = engine
        captured["force"] = force
        captured["concurrency"] = concurrency

    monkeypatch.setattr("pursue_index.ocr.pipeline.ocr_all", _fake_ocr_all)

    from pursue_index.cli.commands import app

    result = CliRunner().invoke(
        app,
        ["ocr", "run", "--manifest", str(manifest_path),
         "--engine", "llm", "--concurrency", "6"],
    )
    assert result.exit_code == 0, result.output
    assert captured["concurrency"] == 6
    assert captured["engine"] == "llm"
