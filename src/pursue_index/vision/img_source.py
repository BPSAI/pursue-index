"""Where an IMG card's bytes are read from for the vision stage.

The downloader writes an IMG asset to ``images/<card_id>/<asset_filename>``,
but not every card has that copy on disk (release-1 FBI photos live only in
the R2 mirror, ``r2-mirror/archive/<byte_sha256>.<ext>``). A mirror copy is
trusted only after its sha256 matches the registry's newest ``byte_sha256``
for the card, so a corrupt or stale mirror file is never described.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pursue_index.config import settings
from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import CardMetadata

_CHUNK = 1 << 20


def default_registry_path() -> Path:
    from pursue_index.paths import repo_root

    return repo_root() / "data" / "asset-bytes-registry.jsonl"


def newest_registry_sha(card_id: str, registry_path: Path) -> str | None:
    """``byte_sha256`` of the card's newest (last) registry row, or ``None``."""
    if not registry_path.exists():
        return None
    sha: str | None = None
    with registry_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("card_id") == card_id and row.get("byte_sha256"):
                sha = str(row["byte_sha256"])
    return sha


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _mirror_path(card: CardMetadata) -> tuple[Path | None, str | None]:
    """The verified mirror copy for ``card``, else ``(None, why not)``."""
    sha = newest_registry_sha(card.card_id, default_registry_path())
    if sha is None:
        return None, "no registry row for the mirror fallback"
    ext = Path(card.asset_filename or "").suffix
    mirror = settings.r2_mirror_dir / "archive" / f"{sha}{ext}"
    if not mirror.is_file():
        return None, f"no file at the mirror path {mirror}"
    actual = _file_sha256(mirror)
    if actual != sha:
        return None, f"mirror file sha256 {actual} != registry byte_sha256 {sha}"
    return mirror, None


def resolve_img_path(card: CardMetadata) -> tuple[Path | None, str | None]:
    """``(path, None)`` for the bytes to read, or ``(None, reason)``.

    An existing ``images/`` copy always wins. Otherwise the verified mirror
    copy. A card with no downloadable asset gets ``(None, "no asset bytes")``.
    """
    primary = asset_path_for(card)
    if primary is None:
        return None, "no asset bytes"
    if primary.is_file():
        return primary, None
    mirror, why = _mirror_path(card)
    if mirror is None:
        return None, f"no images/ copy and {why}"
    return mirror, None
