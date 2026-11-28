"""Source-side file I/O for the image mirror stage: a no-follow open, a hash and a staged copy.

Pure filesystem I/O only: no network, no credentials.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import tempfile
from pathlib import Path


def open_source_nofollow(src: Path):
    """Open ``src`` read-only without following a symlink; ``None`` if one is there now."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None
        raise
    return os.fdopen(fd, "rb")


def sha256_stream(inp) -> str:
    h = hashlib.sha256()
    while chunk := inp.read(1 << 20):
        h.update(chunk)
    return h.hexdigest()


def stage_temp(inp, target: Path) -> Path:
    """Copy the open source ``inp`` into a fresh, exclusively created temp file beside ``target``."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            shutil.copyfileobj(inp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp
