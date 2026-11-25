"""Superseding a sidecar: the new pass in front, the old one kept.

Split from ``redescribe``. ``supersede_sidecar`` builds the result, ``dry_supersede``
rehearses it with placeholder pages, and ``write_atomic`` lands it.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.sidecar import (
    DEFAULT_CONTEXT,
    Observation,
    SidecarPage,
    validate_sidecar,
)

METHOD = "vision-run"


def supersede_sidecar(
    existing: dict[str, Any], new_pages: list[dict[str, Any]], *,
    model: str, now: str,
) -> dict[str, Any]:
    """``existing`` with a new pass in front and the old one kept, not dropped.

    Key order is preserved (the new values take the old keys' places), so the
    diff of a re-described file is the pass, the pages and one new key.
    """
    old_pass = existing.get("our_pass") or {}
    superseded = list(existing.get("superseded_passes") or [])
    superseded.append({
        "our_pass": old_pass, "pages": existing.get("pages", []), "superseded_at": now,
    })
    new = dict(existing)
    new["our_pass"] = {
        "model": model, "method": METHOD,
        "context": DEFAULT_CONTEXT, "described_at": now,
    }
    new["pages"] = new_pages
    new["superseded_passes"] = superseded
    validate_sidecar(new)
    return new


def _fsync_dir(directory: Path) -> None:
    """Flush a directory entry so a completed rename survives a crash."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_atomic(path: Path, doc: dict[str, Any]) -> None:
    """Write ``doc`` to ``path`` through an unpredictably named temp file beside it.

    The file keeps the target's mode (0644 for a new one) and is synced before the
    rename, the directory after it. A target that is a symlink is refused before
    anything is written.
    """
    text = json.dumps(doc, indent=2) + "\n"
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        mode = 0o644
    else:
        if stat.S_ISLNK(st.st_mode):
            raise OSError(f"refusing to write through a symlink: {path}")
        mode = stat.S_IMODE(st.st_mode)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as fh:
            tmp = Path(fh.name)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        raise


def dry_supersede(
    existing: dict[str, Any], card_items: list[EligibleItem], model: str
) -> str | None:
    """Why ``existing`` (just re-read) could not be superseded, or None.

    Validates it and runs the real ``supersede_sidecar`` on placeholder pages,
    so a sidecar that went bad since planning is refused before the card's
    first paid call, not after its last.
    """
    try:
        validate_sidecar(existing)
        # Built from the page model, so a schema change fails here, loudly.
        placeholders = [
            {**SidecarPage(
                page=i.page, observations=[Observation(claim="placeholder")]
            ).model_dump(), "row_key": i.row_key}
            for i in card_items
        ]
        supersede_sidecar(existing, placeholders, model=model, now="dry-run")
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


