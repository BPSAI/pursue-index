"""Write a text file atomically: a temp file in the same directory, then ``os.replace``."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["write_text_atomic"]


def write_text_atomic(path: Path, text: str, mode: int = 0o644) -> None:
    """Replace ``path`` with ``text``; on any failure the old file is untouched.

    No temp file is left behind, whether the write or the replace fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
