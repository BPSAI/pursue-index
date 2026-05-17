"""Tests for ``scripts/wayback_save.py``.

The wayback-save script reads a list of URLs (sitemap-xml or CLI arg)
and submits each to ``https://web.archive.org/save/<url>``. Strict-
sequential with a configurable delay between calls (Wayback rate-
limits hard). Idempotent — skips URLs saved within a configurable
freshness window (default 24 h).

These tests cover the pure helpers (URL parsing, freshness gating,
plan building) without making any real network calls.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import wayback_save  # noqa: E402


# --- sitemap parsing --------------------------------------------------


_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://pursueindex.com/</loc></url>
  <url><loc>https://pursueindex.com/about</loc></url>
  <url><loc>https://pursueindex.com/methodology</loc></url>
</urlset>
""".strip()


_SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://pursueindex.com/sitemap-0.xml</loc></sitemap>
</sitemapindex>
""".strip()


def test_parse_sitemap_urlset_returns_loc_values() -> None:
    """A urlset sitemap yields every <loc>."""
    urls = wayback_save.parse_sitemap_urls(_SITEMAP_XML)
    assert urls == [
        "https://pursueindex.com/",
        "https://pursueindex.com/about",
        "https://pursueindex.com/methodology",
    ]


def test_parse_sitemap_index_returns_sitemap_locs() -> None:
    """A sitemapindex yields each child <sitemap><loc>."""
    urls = wayback_save.parse_sitemap_urls(_SITEMAP_INDEX_XML)
    assert urls == ["https://pursueindex.com/sitemap-0.xml"]


def test_parse_sitemap_strips_whitespace() -> None:
    xml = (
        '<?xml version="1.0"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url><loc>\n    https://pursueindex.com/x  \n  </loc></url>\n'
        '</urlset>'
    )
    assert wayback_save.parse_sitemap_urls(xml) == ["https://pursueindex.com/x"]


# --- freshness gating -------------------------------------------------


def test_is_fresh_returns_true_within_window() -> None:
    """A timestamp inside the freshness window is considered fresh."""
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    saved_at = now - timedelta(hours=3)
    assert wayback_save.is_fresh(saved_at, now=now, window=timedelta(hours=24))


def test_is_fresh_returns_false_outside_window() -> None:
    """A timestamp older than the window is stale."""
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    saved_at = now - timedelta(hours=25)
    assert not wayback_save.is_fresh(saved_at, now=now, window=timedelta(hours=24))


def test_is_fresh_handles_none() -> None:
    """No prior save => not fresh (must save)."""
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    assert not wayback_save.is_fresh(None, now=now, window=timedelta(hours=24))


# --- save URL construction -------------------------------------------


def test_save_url_uses_wayback_prefix() -> None:
    """The save endpoint is `https://web.archive.org/save/<url>`."""
    assert (
        wayback_save.build_save_url("https://pursueindex.com/about")
        == "https://web.archive.org/save/https://pursueindex.com/about"
    )


def test_save_url_preserves_query_and_fragment() -> None:
    """Query strings + fragments are passed through verbatim."""
    src = "https://pursueindex.com/search?q=roswell#hit-1"
    assert (
        wayback_save.build_save_url(src)
        == f"https://web.archive.org/save/{src}"
    )


# --- plan filtering --------------------------------------------------


def test_build_plan_filters_fresh_urls() -> None:
    """URLs saved within the window are skipped; stale ones are kept."""
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    history = {
        "https://pursueindex.com/about": now - timedelta(hours=2),  # fresh
        "https://pursueindex.com/methodology": now - timedelta(hours=48),  # stale
        # https://pursueindex.com/ has no history → must save
    }
    urls = [
        "https://pursueindex.com/",
        "https://pursueindex.com/about",
        "https://pursueindex.com/methodology",
    ]
    plan = wayback_save.build_plan(
        urls, history=history, now=now, window=timedelta(hours=24)
    )
    assert plan == [
        "https://pursueindex.com/",
        "https://pursueindex.com/methodology",
    ]


def test_build_plan_preserves_input_order() -> None:
    now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    urls = [
        "https://pursueindex.com/methodology",
        "https://pursueindex.com/about",
        "https://pursueindex.com/",
    ]
    plan = wayback_save.build_plan(
        urls, history={}, now=now, window=timedelta(hours=24)
    )
    assert plan == urls


def test_build_plan_empty_input_returns_empty() -> None:
    plan = wayback_save.build_plan(
        [], history={}, now=datetime.now(UTC), window=timedelta(hours=24)
    )
    assert plan == []


# --- live-URL gating -------------------------------------------------


def test_should_skip_origin_status_skips_4xx_and_5xx() -> None:
    """Wayback won't accept 404/500 origin URLs — skip them."""
    assert wayback_save.should_skip_origin_status(404)
    assert wayback_save.should_skip_origin_status(500)
    assert wayback_save.should_skip_origin_status(503)


def test_should_skip_origin_status_keeps_2xx_3xx() -> None:
    """2xx and 3xx (redirect chain to live page) are saved."""
    assert not wayback_save.should_skip_origin_status(200)
    assert not wayback_save.should_skip_origin_status(301)
    assert not wayback_save.should_skip_origin_status(308)
