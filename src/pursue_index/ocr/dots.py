"""dots.mocr OCR engine — local, content-filter-backstop, via a subprocess bridge.

dots.mocr (rednote-hilab, MIT) runs locally on the GPU and has **no content
filter**, so it can transcribe the rare page Anthropic's output filter blocks
(the `llm` engine 400s with "Output blocked by content filtering policy" on
some sensitive declassified docs — e.g. the CIA U-2/OXCART history). It is a
layout parser, not a primary engine: it cannot honour the `[REDACTED]` /
`[ILLEGIBLE]` sentinel contract, so it is a backstop, not a replacement for
Sonnet 4.6.

dots needs a torch/transformers stack incompatible with pursue-index's venv, so
it runs in an **isolated venv** reached via a **persistent worker subprocess**:
the ~6 GB model loads ONCE per run, then this adapter streams page images to it
over a stdin/stdout line protocol (one temp-PNG path in, one JSON line out).

Operator config (env):
  PURSUE_DOTS_PYTHON  — python in the isolated dots venv (REQUIRED).
  PURSUE_DOTS_MODEL   — dots.mocr model dir, period-free path (REQUIRED).
  PURSUE_DOTS_WORKER  — worker script (default: repo ``scripts/dots_worker.py``).

The seam matches ``ocr.pipeline.ocr_image`` / ``ocr.llm.ocr_image``:
``ocr_image(img) -> (text, confidence)``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from PIL import Image

from pursue_index import get_logger

log = get_logger(__name__)

# dots has no self-rated confidence (layout parser). Emit a fixed nominal so the
# auto-mode threshold + provenance ledger see a stable value; the engine tag
# (``dots-mocr``) is what carries the "this was the backstop" signal.
_DOTS_CONFIDENCE = 70.0

_worker: _DotsWorker | None = None
# The persistent worker has a single stdin/stdout channel. Serialize all access
# so concurrent callers (e.g. several cards in the llm→dots fallback run hitting
# a content-filter page at once) can't interleave and corrupt the line protocol.
_lock = threading.Lock()


def _worker_script_default() -> str:
    # src/pursue_index/ocr/dots.py -> repo root is parents[3]
    return str(Path(__file__).resolve().parents[3] / "scripts" / "dots_worker.py")


class _DotsWorker:
    """A persistent dots.mocr subprocess in the isolated venv.

    Spawns ``$PURSUE_DOTS_PYTHON scripts/dots_worker.py --model <dir>`` once;
    the worker loads the model, then serves one request per line: it reads a
    PNG path on stdin and writes ``{"text": ..., "confidence": ...}`` on stdout.
    """

    def __init__(self) -> None:
        py = os.environ.get("PURSUE_DOTS_PYTHON")
        if not py:
            raise RuntimeError(
                "dots engine requires PURSUE_DOTS_PYTHON (python in the isolated "
                "dots venv). It is unset. See src/pursue_index/ocr/dots.py."
            )
        model = os.environ.get("PURSUE_DOTS_MODEL")
        if not model:
            raise RuntimeError(
                "dots engine requires PURSUE_DOTS_MODEL (path to the dots.mocr "
                "model dir, period-free). It is unset. See src/pursue_index/ocr/dots.py."
            )
        worker = os.environ.get("PURSUE_DOTS_WORKER") or _worker_script_default()
        log.info("ocr.dots.worker.start", python=py, worker=worker, model=model)
        self.proc = subprocess.Popen(
            [py, worker, "--model", model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # worker logs (model load, warnings) flow to our stderr
            text=True,
            bufsize=1,  # line-buffered
        )

    def ocr(self, img: Image.Image) -> tuple[str, float]:
        if self.proc.poll() is not None:
            raise RuntimeError(
                f"dots worker exited (code {self.proc.returncode}) before request"
            )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp_path = tf.name
        try:
            rgb = img if img.mode == "RGB" else img.convert("RGB")
            rgb.save(tmp_path, format="PNG")
            assert self.proc.stdin is not None and self.proc.stdout is not None
            self.proc.stdin.write(tmp_path + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("dots worker closed stdout without a response")
            payload: dict[str, Any] = json.loads(line)
            if "error" in payload:
                raise RuntimeError(f"dots worker error: {payload['error']}")
            return str(payload.get("text", "")), float(
                payload.get("confidence", _DOTS_CONFIDENCE)
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                if self.proc.stdin is not None:
                    self.proc.stdin.close()  # EOF → worker exits its read loop
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()


def _get_worker() -> _DotsWorker:
    global _worker
    if _worker is None or _worker.proc.poll() is not None:
        _worker = _DotsWorker()
    return _worker


def ocr_image(img: Image.Image) -> tuple[str, float]:
    """Return ``(text, confidence)`` for a single page image via dots.mocr.

    Lazily starts the persistent worker on first call (model loads once), then
    reuses it for every subsequent page in the run. Thread-safe: access to the
    single worker channel is serialized under ``_lock``.
    """
    with _lock:
        return _get_worker().ocr(img)


def shutdown() -> None:
    """Stop the persistent worker (idempotent). Optional; the process exits
    on its own when pursue-index exits."""
    global _worker
    if _worker is not None:
        _worker.close()
        _worker = None
