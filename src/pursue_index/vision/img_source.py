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
import re
from pathlib import Path

from pursue_index.config import settings
from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import CardMetadata

_CHUNK = 1 << 20
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def default_registry_path() -> Path:
    from pursue_index.paths import repo_root

    return repo_root() / "data" / "asset-bytes-registry.jsonl"


def load_registry(registry_path: Path | None = None) -> dict[str, str]:
    """``{card_id: byte_sha256}`` of each card's newest (last) registry row.

    Read once per planning call and handed to ``resolve_img_path``, so the
    cost is one pass over the registry however many cards are resolved.
    """
    path = registry_path if registry_path is not None else default_registry_path()
    newest: dict[str, str] = {}
    if not path.exists():
        return newest
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("card_id") and row.get("byte_sha256"):
                newest[str(row["card_id"])] = str(row["byte_sha256"])
    return newest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def _cached_file_sha256(path: Path) -> str:
    """``_file_sha256`` memoized per ``(path, size, mtime_ns)`` for this process.

    Planning and the no-spend preview call this for every mirror card; a file
    that has not changed is hashed once. This only speeds up *planning*: the
    bytes actually loaded are re-hashed by ``render.load_image_for``.
    """
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    sha = _SHA_CACHE.get(key)
    if sha is None:
        sha = _SHA_CACHE[key] = _file_sha256(path)
    return sha


def expected_sha_for(
    card: CardMetadata, path: Path | None, registry: dict[str, str]
) -> str | None:
    """The sha256 ``path`` must still match at load time, or None.

    Only a mirror copy needs it (an ``images/`` copy is trusted as before): a
    path other than the card's own ``images/`` path is the verified mirror
    file, whose registry sha is what planning verified.
    """
    if path is None or path == asset_path_for(card):
        return None
    return registry.get(card.card_id)


def _mirror_path(
    card: CardMetadata, registry: dict[str, str]
) -> tuple[Path | None, str | None]:
    """The verified mirror copy for ``card``, else ``(None, why not)``."""
    sha = registry.get(card.card_id)
    if sha is None:
        return None, "no registry row for the mirror fallback"
    if not _SHA256_RE.fullmatch(sha):
        return None, f"registry byte_sha256 {sha!r} is not 64 lowercase hex digits"
    ext = Path(card.asset_filename or "").suffix
    mirror = settings.r2_mirror_dir / "archive" / f"{sha}{ext}"
    if not mirror.is_file():
        return None, f"no file at the mirror path {mirror}"
    actual = _cached_file_sha256(mirror)
    if actual != sha:
        return None, f"mirror file sha256 {actual} != registry byte_sha256 {sha}"
    return mirror, None


def resolve_img_path(
    card: CardMetadata, registry: dict[str, str] | None = None
) -> tuple[Path | None, str | None]:
    """``(path, None)`` for the bytes to read, or ``(None, reason)``.

    An existing ``images/`` copy always wins. Otherwise the verified mirror
    copy. ``registry`` is the preloaded ``load_registry()`` map (loaded here
    only when absent, and only if the mirror is needed). A card with no downloadable asset gets ``(None, "no asset bytes")``.
    """
    primary = asset_path_for(card)
    if primary is None:
        return None, "no asset bytes"
    if primary.is_file():
        return primary, None
    mirror, why = _mirror_path(card, load_registry() if registry is None else registry)
    if mirror is None:
        return None, f"no images/ copy and {why}"
    return mirror, None
