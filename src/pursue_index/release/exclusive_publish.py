"""Publish a verified temp file into a content-addressed store without ever overwriting.

A hard link fails if the target exists; where the filesystem refuses hard
links (CIFS can), an ``O_EXCL`` create plus a copy gives the same guarantee.
A target that appeared meanwhile is hashed and reported, never touched, and
the temp file is always removed.

Pure filesystem I/O only: no network, no credentials.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

_CHUNK = 1 << 20

PUBLISHED = "published"
EXISTING_MATCH = "existing_match"
EXISTING_MISMATCH = "existing_mismatch"


def sha256_file(path: Path) -> str:
    """Hex sha256 of ``path``, read in 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _copy_exclusive(tmp: Path, target: Path) -> None:
    """Stream ``tmp`` into a new ``target``; ``FileExistsError`` if it exists."""
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as out, tmp.open("rb") as src:
            shutil.copyfileobj(src, out, _CHUNK)
    except BaseException:
        target.unlink(missing_ok=True)  # our own partial file, created just above
        raise


def publish_exclusive(tmp: Path, target: Path, sha: str) -> tuple[str, str]:
    """Publish the verified ``tmp`` as ``target``; returns ``(status, actual_sha)``.

    ``status`` is ``PUBLISHED``, or, when ``target`` already existed,
    ``EXISTING_MATCH`` / ``EXISTING_MISMATCH`` with the existing file's sha.
    """
    try:
        try:
            os.link(tmp, target)
        except FileExistsError:
            raise
        except OSError:
            _copy_exclusive(tmp, target)
    except FileExistsError:
        actual = sha256_file(target)
        return (EXISTING_MATCH if actual == sha else EXISTING_MISMATCH), actual
    finally:
        tmp.unlink(missing_ok=True)
    return PUBLISHED, sha
