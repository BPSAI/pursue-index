"""Which earlier registry rows an asset is compared with.

A card can be backed by several assets (a PDF and videos hosted elsewhere), so the
card's newest row is not necessarily this asset's. Shared by the archive scripts and
the tranche path.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

__all__ = ["file_type", "rows_of_asset"]


def file_type(asset_filename: Any, asset_url: Any) -> str:
    """Lowercase extension of the filename, or of the URL path when there is no filename."""
    name = str(asset_filename or "")
    if not name:
        name = urlparse(str(asset_url or "")).path
    return PurePosixPath(name).suffix.lower()


def rows_of_asset(rows: list[dict[str, Any]] | None, asset_url: Any, asset_filename: Any = None):
    """The earlier rows an asset is compared with, oldest first.

    A card's asset is identified by ``(card_id, asset_url)``. With no row at that URL (the
    asset moved), fall back to the card's rows of the same file type, newest last; with
    none of that type either, the asset is net-new (empty)."""
    url = str(asset_url)
    same = [r for r in rows or [] if str(r.get("asset_url")) == url]
    if same:
        return same
    kind = file_type(asset_filename, asset_url)
    if not kind:
        return []
    return [r for r in rows or [] if file_type(r.get("asset_filename"), r.get("asset_url")) == kind]
