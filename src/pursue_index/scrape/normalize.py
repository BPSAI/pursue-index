"""Normalization helpers for CSV values.

The source CSV has a few quirks that are easier to handle in one place:

* Titles wrapped in leading/trailing newlines.
* Type column has 6 rows with ``"PDF "`` (trailing space) vs ``"PDF"``.
* ``"N/A"`` used as a sentinel for missing dates and locations.
* ``Redaction`` column is the string ``"True"`` or empty (no ``"False"``).
"""

from __future__ import annotations

import hashlib
import re
from typing import cast
from urllib.parse import urlparse

from pursue_index.scrape.types import AssetType

_NA_VALUES = {"", "n/a", "na", "none", "null", "nan"}


def clean_str(value: object) -> str | None:
    """Strip whitespace and treat blanks/N/A sentinels as ``None``."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in _NA_VALUES:
        return None
    return s


def clean_title(value: object) -> str:
    """Titles in the CSV often have wrapping ``\\n`` and irregular whitespace."""
    s = clean_str(value)
    if not s:
        return ""
    # Collapse internal whitespace, strip surrounding underscores/spaces.
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_asset_type(value: object) -> AssetType:
    """Normalize the ``Type`` column to a known asset type."""
    s = clean_str(value)
    if not s:
        raise ValueError("Asset type is required")
    s = s.upper().strip()
    if s in {"PDF", "VID", "IMG"}:
        return cast(AssetType, s)
    raise ValueError(f"Unknown asset type: {value!r}")


def parse_redacted(value: object) -> bool:
    """The ``Redaction`` column is ``True`` or empty. Any non-empty truthy = True."""
    s = clean_str(value)
    if not s:
        return False
    return s.lower() in {"true", "yes", "y", "1"}


def filename_from_url(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path
    return path.rsplit("/", 1)[-1] or None


def stable_card_id(asset_url: str | None, title: str) -> str:
    """Deterministic id; survives re-fetches as long as URL or title is stable.

    Prefer the asset URL because it's the most stable identifier; fall back to
    title for entries that have no asset (rare, but possible for metadata-only
    cards in future tranches).
    """
    seed = asset_url or title
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
