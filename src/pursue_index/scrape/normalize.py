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
    """Normalize the ``Type`` column to a known asset type.

    AUD added Sprint 4f after upstream relabeled the NASA Gemini 7
    audio card (card_id 167f6a21c7238d0c) from VID → AUD between
    tranche c9cc83fcaf43 and f75e2f7de0ff. AUD semantics mirror VID:
    DVIDS-hosted, no asset_url, metadata-only card. The download +
    OCR lanes skip both types identically.
    """
    s = clean_str(value)
    if not s:
        raise ValueError("Asset type is required")
    s = s.upper().strip()
    if s in {"PDF", "VID", "IMG", "AUD"}:
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


_CLASSIFICATION_PATTERN = re.compile(
    # Match the canonical US/NATO levels as standalone words. "Top Secret"
    # must come before "Secret" so the longer phrase wins on greedy match.
    # Word boundary on both sides prevents matches inside larger words.
    r"\b(Top Secret|Secret|Confidential|Restricted|Unclassified)\b",
    re.IGNORECASE,
)


def extract_classification(alt_text: str | None) -> str | None:
    """Pull the original document classification out of upstream alt-text.

    Upstream alt-text often reads like "Declassified Secret document
    from Air Materiel Command." or "Declassified Top Secret document
    from the U.S. Air Force Directorate of Intelligence." Only ~13% of
    cards in tranche c9cc83fcaf43 have a level keyword — the rest say
    "Declassified" without a level, or describe the cover/folder rather
    than the document. We surface what's explicit and stay silent on
    the rest rather than guessing.
    """
    if not alt_text:
        return None
    m = _CLASSIFICATION_PATTERN.search(alt_text)
    if not m:
        return None
    return m.group(1).title()
