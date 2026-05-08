"""Manifest persistence: load/save JSON with atomic write semantics."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pursue_index.scrape.types import Manifest


def save_manifest(manifest: Manifest, path: Path) -> Path:
    """Write the manifest to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump_json(indent=2, by_alias=True)

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return path


def load_manifest(path: Path) -> Manifest:
    """Read a manifest from disk."""
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return Manifest.model_validate(data)
