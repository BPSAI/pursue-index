"""Tests for OCR pipeline concurrency selection.

Sprint 4r-async: the canonical ``pursue ocr run`` pipeline was historically
serial for LLM/auto engines (concurrency=1) "so the API call stays
un-thrashed". Empirically this caps throughput at ~3 pages/min, making a
full-corpus re-OCR ~19h instead of ~5h. The proven
``scripts/reocr_altered.py`` ThreadPoolExecutor pattern is fine against
Anthropic's API at concurrency=4-8 with default SDK retries.

These tests pin the new contract:

- ``_concurrency_for("llm" | "auto")`` defaults to 4
- Operators can override via ``PURSUE_OCR_LLM_CONCURRENCY`` env var
- Surya stays at 1 (single GPU can't truly parallelize)
- Tesseract behavior unchanged (CPU-bound, cpu_count cap)
"""

from __future__ import annotations

import pytest

from pursue_index.ocr import pipeline as ocr_pipeline


# ---------------------------------------------------------------------------
# Cycle 1: _concurrency_for env-var support for LLM/auto engines
# ---------------------------------------------------------------------------


def test_concurrency_for_llm_defaults_to_four(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var set → LLM concurrency is 4 (4x speedup vs prior serial)."""
    monkeypatch.delenv("PURSUE_OCR_LLM_CONCURRENCY", raising=False)
    assert ocr_pipeline._concurrency_for("llm") == 4


def test_concurrency_for_llm_reads_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator override via ``PURSUE_OCR_LLM_CONCURRENCY`` env var."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "8")
    assert ocr_pipeline._concurrency_for("llm") == 8


def test_concurrency_for_auto_matches_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto engine uses LLM fallback so it inherits the same concurrency."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "6")
    assert ocr_pipeline._concurrency_for("auto") == 6


# ---------------------------------------------------------------------------
# Cycle 2: surya stays serial; tesseract preserved
# ---------------------------------------------------------------------------


def test_concurrency_for_surya_stays_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surya is single-GPU; LLM env var must not bleed into surya path."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "8")
    assert ocr_pipeline._concurrency_for("surya") == 1


def test_concurrency_for_tesseract_uses_cpu_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tesseract is CPU-bound: cap at min(4, cpu_count). LLM env irrelevant."""
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "8")
    expected = min(4, ocr_pipeline.os.cpu_count() or 1)
    assert ocr_pipeline._concurrency_for("tesseract") == expected


# ---------------------------------------------------------------------------
# Cycle 3: ocr_all accepts an explicit `concurrency` override
# ---------------------------------------------------------------------------


def test_ocr_all_uses_explicit_concurrency_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr_all(concurrency=N)`` constructs the Semaphore with ``N``,
    bypassing both the env-var default and ``_concurrency_for``."""
    import asyncio
    from pursue_index.scrape.types import Manifest

    captured: list[int] = []
    real_semaphore = asyncio.Semaphore

    def _capture(value: int) -> asyncio.Semaphore:
        captured.append(value)
        return real_semaphore(value)

    monkeypatch.setattr(ocr_pipeline.asyncio, "Semaphore", _capture)
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "4")  # default ignored

    empty = Manifest(
        source_url="https://example.com/x.csv",
        fetched_at="2026-05-22T00:00:00Z",
        csv_sha256="0" * 64,
        cards=[],
    )
    asyncio.run(ocr_pipeline.ocr_all(empty, engine="llm", concurrency=7))

    assert captured == [7], (
        f"Semaphore should be built with override=7, got {captured}"
    )


def test_ocr_all_falls_back_to_concurrency_for_when_override_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr_all(concurrency=None)`` (default) uses ``_concurrency_for``."""
    import asyncio
    from pursue_index.scrape.types import Manifest

    captured: list[int] = []
    real_semaphore = asyncio.Semaphore

    def _capture(value: int) -> asyncio.Semaphore:
        captured.append(value)
        return real_semaphore(value)

    monkeypatch.setattr(ocr_pipeline.asyncio, "Semaphore", _capture)
    monkeypatch.setenv("PURSUE_OCR_LLM_CONCURRENCY", "3")

    empty = Manifest(
        source_url="https://example.com/x.csv",
        fetched_at="2026-05-22T00:00:00Z",
        csv_sha256="0" * 64,
        cards=[],
    )
    asyncio.run(ocr_pipeline.ocr_all(empty, engine="llm"))

    assert captured == [3], (
        f"Semaphore should fall back to env-var default=3, got {captured}"
    )


# ---------------------------------------------------------------------------
# Cycle 4: pursue ocr run --concurrency CLI flag
# ---------------------------------------------------------------------------


def test_cli_ocr_run_passes_concurrency_through(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pursue ocr run --concurrency N`` flows N into ``ocr_all``."""
    from typer.testing import CliRunner

    # Empty-but-valid manifest file
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        '{"source_url": "https://example.com/x.csv",'
        ' "fetched_at": "2026-05-22T00:00:00Z",'
        ' "csv_sha256": "' + "0" * 64 + '",'
        ' "cards": []}'
    )

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
