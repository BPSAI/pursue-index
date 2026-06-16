"""Tests for the dots.mocr subprocess-bridge OCR adapter.

The real worker needs the isolated GPU venv + the ~6 GB model, so these tests
point ``PURSUE_DOTS_PYTHON`` at the current interpreter and ``PURSUE_DOTS_WORKER``
at a tiny *fake* worker that speaks the same stdin(PNG-path)/stdout(JSON-line)
protocol — exercising the adapter's process management, image round-trip, error
handling, and worker reuse without any model.
"""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from pursue_index.ocr import dots as ocr_dots

_FAKE_WORKER = textwrap.dedent(
    """
    import sys, json, os
    # Echo a deterministic transcription per page-image path.
    for line in sys.stdin:
        p = line.strip()
        if not p:
            break
        print(json.dumps({"text": "FAKE:" + os.path.basename(p)[:6], "confidence": 88}))
        sys.stdout.flush()
    """
)

_ERROR_WORKER = textwrap.dedent(
    """
    import sys, json
    for line in sys.stdin:
        if not line.strip():
            break
        print(json.dumps({"error": "model failed to load"}))
        sys.stdout.flush()
    """
)


@pytest.fixture(autouse=True)
def _reset_worker() -> Iterator[None]:
    ocr_dots.shutdown()
    yield
    ocr_dots.shutdown()


def _install_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    worker = tmp_path / "fake_worker.py"
    worker.write_text(body)
    monkeypatch.setenv("PURSUE_DOTS_PYTHON", sys.executable)
    monkeypatch.setenv("PURSUE_DOTS_WORKER", str(worker))
    monkeypatch.setenv("PURSUE_DOTS_MODEL", "/unused/in/fake")


def test_ocr_image_roundtrips_via_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_worker(monkeypatch, tmp_path, _FAKE_WORKER)
    text, conf = ocr_dots.ocr_image(Image.new("RGB", (12, 12)))
    assert text.startswith("FAKE:")
    assert conf == pytest.approx(88.0)


def test_worker_error_payload_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_worker(monkeypatch, tmp_path, _ERROR_WORKER)
    with pytest.raises(RuntimeError, match="model failed to load"):
        ocr_dots.ocr_image(Image.new("RGB", (12, 12)))


def test_missing_python_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PURSUE_DOTS_PYTHON", raising=False)
    with pytest.raises(RuntimeError, match="PURSUE_DOTS_PYTHON"):
        ocr_dots.ocr_image(Image.new("RGB", (12, 12)))


def test_persistent_worker_reused_across_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The model must load once: repeated calls reuse the same subprocess."""
    _install_worker(monkeypatch, tmp_path, _FAKE_WORKER)
    ocr_dots.ocr_image(Image.new("RGB", (10, 10)))
    pid1 = ocr_dots._worker.proc.pid  # type: ignore[union-attr]
    ocr_dots.ocr_image(Image.new("RGB", (10, 10)))
    pid2 = ocr_dots._worker.proc.pid  # type: ignore[union-attr]
    assert pid1 == pid2


def test_pipeline_routes_dots_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pipeline dispatches engine='dots' to the dots adapter."""
    from pursue_index.ocr import pipeline

    monkeypatch.setattr(ocr_dots, "ocr_image", lambda img: ("DOTS-TEXT", 70.0))
    fn = pipeline._engine_ocr_image("dots")
    text, conf = fn(Image.new("RGB", (4, 4)))
    assert text == "DOTS-TEXT"
    assert conf == pytest.approx(70.0)


def test_dots_runs_serially() -> None:
    """dots must run at concurrency 1 — one persistent worker, one channel."""
    from pursue_index.ocr import pipeline

    assert pipeline._concurrency_for("dots") == 1
