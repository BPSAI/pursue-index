"""Run the byte classifier in a resource-limited subprocess.

The parser and pypdf run on externally sourced PDFs; a worker with an
address-space ceiling and a wall-clock timeout contains whatever the
in-process caps (``pdf_limits``) miss. ``run_worker`` returns the worker's
verdict text, or ``None`` on a crash, timeout, non-zero exit or unexpected
output -- the caller maps ``None`` to ``content-changed``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pursue_index import pdf_limits

__all__ = ["WORKER_MEMORY_BYTES", "run_worker"]

WORKER_MODULE = "pursue_index.classify_worker"
# Both files are read whole (each up to MAX_FILE_BYTES, 512 MiB) and pypdf
# copies each into a BytesIO, so ~2 GiB of byte buffers plus the interpreter,
# pypdf and parse structures: 6 GiB of address space is above that budget yet
# far below a runaway allocation. RLIMIT_AS counts virtual, not resident.
WORKER_MEMORY_BYTES = 6 * 1024 * 1024 * 1024
_VERDICTS = ("metadata-only", "content-changed")
_LOG = logging.getLogger(__name__)


# The worker parses untrusted PDFs, so it gets no credentials: only what the
# interpreter and locale handling need.
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "VIRTUAL_ENV")


def _env() -> dict[str, str]:
    paths = [os.path.abspath(p) for p in sys.path if p]
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    return {**env, "PYTHONPATH": os.pathsep.join(paths)}


def run_worker(
    old_path: Path, new_path: Path, old_sha256: str | None = None, new_sha256: str | None = None,
) -> str | None:
    # -P: never prepend the cwd to sys.path. The cwd is a fresh empty
    # directory, not the shared temp root, so nothing a neighbor drops can be
    # imported; the inputs are made absolute because the cwd is not the caller's.
    cmd = [sys.executable, "-P", "-m", WORKER_MODULE,
           str(Path(old_path).resolve()), str(Path(new_path).resolve()),
           "--memory-bytes", str(WORKER_MEMORY_BYTES)]
    for flag, sha in (("--old-sha256", old_sha256), ("--new-sha256", new_sha256)):
        if sha is not None:
            cmd += [flag, sha]
    try:
        with tempfile.TemporaryDirectory(prefix="classify-worker-") as scratch:
            done = subprocess.run(
                cmd, capture_output=True, text=True, check=False, env=_env(),
                cwd=scratch, timeout=pdf_limits.TIME_BUDGET_SECONDS,
            )
    except subprocess.TimeoutExpired:
        _LOG.warning("classify worker fail-safe (worker-timeout): over %ss",
                     pdf_limits.TIME_BUDGET_SECONDS)
        return None
    out = done.stdout.strip()
    if done.returncode != 0 or out not in _VERDICTS:
        _LOG.warning("classify worker fail-safe (worker-failed): exit %s, %d output bytes",
                     done.returncode, len(out))
        return None
    return out
