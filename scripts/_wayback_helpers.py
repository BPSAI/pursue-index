"""Pure helpers for ``wayback_save.py`` — extracted to keep the main
script slim enough for arch check (target <200 lines / <15 funcs).

Everything here is stdlib-only and free of I/O so the unit tests can
import and exercise these functions without touching the network or
filesystem. The orchestration / I/O lives in ``wayback_save.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

WAYBACK_SAVE_PREFIX = "https://web.archive.org/save/"
SKIPPABLE_STATUS_MIN = 400


# --- sitemap parsing -------------------------------------------------


_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)


def parse_sitemap_urls(xml: str) -> list[str]:
    """Extract <loc> values from a urlset OR sitemapindex XML body.

    Pure-stdlib regex parser — avoids the ``xml.etree`` namespace
    quirk where ``find("loc")`` returns ``None`` unless the caller
    spells the namespace correctly. The pattern is tight enough for
    the well-formed sitemap that Astro emits.
    """
    return [m.group(1).strip() for m in _LOC_RE.finditer(xml)]


# --- freshness gating ------------------------------------------------


def is_fresh(
    saved_at: datetime | None, *, now: datetime, window: timedelta
) -> bool:
    """True if ``saved_at`` is within ``window`` of ``now``.

    A ``None`` saved_at means we've never saved this URL → not fresh.
    """
    if saved_at is None:
        return False
    return now - saved_at < window


# --- save-URL construction -------------------------------------------


def build_save_url(src: str) -> str:
    """``https://web.archive.org/save/<src>`` — passthrough."""
    return f"{WAYBACK_SAVE_PREFIX}{src}"


# --- plan filtering --------------------------------------------------


def build_plan(
    urls: list[str],
    *,
    history: dict[str, datetime],
    now: datetime,
    window: timedelta,
) -> list[str]:
    """Return the subset of ``urls`` that are stale per ``history``.

    Order-preserving. URLs absent from history are kept; URLs whose
    last save is older than ``window`` are kept; URLs saved inside
    the window are skipped.
    """
    return [u for u in urls if not is_fresh(history.get(u), now=now, window=window)]


# --- origin-status gating --------------------------------------------


def should_skip_origin_status(status: int) -> bool:
    """4xx and 5xx origin responses are skipped from the save plan."""
    return status >= SKIPPABLE_STATUS_MIN


# --- DoS posture: --max-urls cap -------------------------------------


def apply_max_urls_cap(
    urls: list[str], *, max_urls: int
) -> tuple[list[str], str | None]:
    """Cap ``urls`` at ``max_urls`` entries.

    Returns ``(capped, warning_message_or_none)``. The warning is a
    GH Actions ``::warning::`` annotation when truncation happens, so
    the operator sees the over-large plan in the run summary. When
    the input is already at or under the cap, the second element is
    ``None`` and the list is returned unchanged.
    """
    if len(urls) <= max_urls:
        return urls, None
    capped = urls[:max_urls]
    warning = (
        f"::warning::wayback-save: plan size {len(urls)} exceeds "
        f"--max-urls cap of {max_urls}; truncated to first {max_urls}"
    )
    return capped, warning
