"""Which parser produced a ``metadata-only`` verdict.

``classifier_id()`` names the pypdf version and a hash of the byte-classifier
sources, and is written onto every auto-approved re-save alias row so the
approval can be audited (and re-run) after the parser changes.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import pypdf

from pursue_index import classify_isolated, pdf_crosscheck, pdf_limits, pdf_update, tranche_bytes

__all__ = ["classifier_id"]

_SOURCES = tuple(Path(m.__file__) for m in (pdf_update, pdf_limits, pdf_crosscheck, classify_isolated, tranche_bytes))


@lru_cache(maxsize=1)
def classifier_id() -> str:
    digest = hashlib.sha256()
    for path in _SOURCES:
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return f"pdf-update-parser/pypdf{pypdf.__version__}/{digest.hexdigest()[:12]}"
