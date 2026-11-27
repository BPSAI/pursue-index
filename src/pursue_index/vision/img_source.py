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
_ARCHIVE_KEY_RE = re.compile(r"archive/([0-9a-f]{64})\.[A-Za-z0-9]+")


def default_registry_path() -> Path:
    from pursue_index.paths import repo_root

    return repo_root() / "data" / "asset-bytes-registry.jsonl"


def load_registry_rows(registry_path: Path | None = None) -> dict[str, dict]:
    """``{card_id: row}`` of each card's newest (last) usable registry row.

    A usable row names a ``card_id`` and a ``byte_sha256``. This is the one
    trust rule for "which bytes is this card": the vision path and the image
    mirror stage both read it.
    """
    path = registry_path if registry_path is not None else default_registry_path()
    newest: dict[str, dict] = {}
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
                newest[str(row["card_id"])] = row
    return newest


class BadArchiveKeyError(ValueError):
    """A registry row whose ``archive_key`` is not ``archive/<its sha>.<ext>``."""


def mirror_path_for(mirror_root: Path, row: dict) -> Path:
    """The one rule for where a registry row's bytes sit in the mirror.

    ``mirror_root / archive_key``, after checking the key is
    ``archive/<64 hex>.<ext>`` and that its sha is the row's ``byte_sha256``.
    The image writer, the preflight and the vision reader all resolve through
    this, so they cannot disagree. Raises ``BadArchiveKeyError``.
    """
    key = row.get("archive_key")
    sha = row.get("byte_sha256")
    m = _ARCHIVE_KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if m is None:
        raise BadArchiveKeyError(f"archive_key {str(key)[:80]!r} is not archive/<sha256>.<ext>")
    if m.group(1) != sha:
        raise BadArchiveKeyError(f"archive_key sha {m.group(1)[:12]} != byte_sha256 {str(sha)[:12]}")
    return mirror_root / key


def img_mirror_path_for(mirror_root: Path, row: dict, asset_filename: str = "") -> Path:
    return mirror_path_for(mirror_root, row)


def load_registry(registry_path: Path | None = None) -> dict[str, dict]:
    """``{card_id: row}`` of each card's newest (last) registry row.

    Read once per planning call and handed to ``resolve_img_path``, so the
    cost is one pass over the registry however many cards are resolved.
    """
    return load_registry_rows(registry_path)


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
    card: CardMetadata, path: Path | None, registry: dict[str, dict]
) -> str | None:
    """The sha256 ``path`` must still match at load time, or None.

    Only a mirror copy needs it (an ``images/`` copy is trusted as before): a
    path other than the card's own ``images/`` path is the verified mirror
    file, whose registry sha is what planning verified.
    """
    if path is None or path == asset_path_for(card):
        return None
    row = registry.get(card.card_id)
    return None if row is None else str(row["byte_sha256"])


def _mirror_path(
    card: CardMetadata, registry: dict[str, dict]
) -> tuple[Path | None, str | None]:
    """The verified mirror copy for ``card``, else ``(None, why not)``."""
    row = registry.get(card.card_id)
    if row is None:
        return None, "no registry row for the mirror fallback"
    sha = str(row["byte_sha256"])
    if not _SHA256_RE.fullmatch(sha):
        return None, f"registry byte_sha256 {sha!r} is not 64 lowercase hex digits"
    if "archive_key" not in row:
        # A legacy row with no key at all: the canonical name, still validated.
        ext = Path(card.asset_filename or "").suffix
        row = {**row, "archive_key": f"archive/{sha}{ext}"}
    try:
        mirror = mirror_path_for(settings.r2_mirror_dir, row)
    except BadArchiveKeyError as exc:
        return None, str(exc)
    if not mirror.is_file():
        return None, f"no file at the mirror path {mirror}"
    actual = _cached_file_sha256(mirror)
    if actual != sha:
        return None, f"mirror file sha256 {actual} != registry byte_sha256 {sha}"
    return mirror, None


def resolve_img_path(
    card: CardMetadata, registry: dict[str, dict] | None = None
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
