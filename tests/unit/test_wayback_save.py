"""Tests for ``scripts/wayback_save.py``.

The wayback-save script reads a list of URLs (sitemap-xml or CLI arg)
and submits each to ``https://web.archive.org/save/<url>``. Strict-
sequential with a configurable delay between calls (Wayback rate-
limits hard). Idempotent — skips URLs saved within a configurable
freshness window (default 24 h).

These tests cover the pure helpers (URL parsing, freshness gating,
plan building, history persistence) without making any real network
calls. Integration-style tests that mock ``urlopen`` and exercise
``main()`` end-to-end live in ``test_wayback_save_integration.py``.
"""

from __future__ import annotations

import json
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


# --- history persistence (round-trip + robustness) ---------------------


def test_load_save_history_round_trip(tmp_path: Path) -> None:
    """save_history + load_history are inverses for ISO datetimes (UTC)."""
    path = tmp_path / "wayback-history.json"
    original = {
        "https://pursueindex.com/": datetime(2026, 5, 17, 10, 0, 0, tzinfo=UTC),
        "https://pursueindex.com/about": datetime(2026, 5, 17, 11, 0, 0, tzinfo=UTC),
    }
    wayback_save.save_history(path, original)
    loaded = wayback_save.load_history(path)
    assert loaded == original


def test_save_history_is_atomic_on_partial_write(
    tmp_path: Path, monkeypatch
) -> None:
    """If the write of the tempfile fails, the original file is left intact.

    M1 (Codex P2): replace ``path.write_text`` with write-temp-then-rename
    so a crashed write can't leave a half-serialized JSON behind. We
    simulate the crash by patching ``Path.replace`` to raise after the
    temp file has been written; the original target file must be unchanged.
    """
    path = tmp_path / "wayback-history.json"
    # Pre-existing content that must survive a failed write.
    original_payload = {"https://pursueindex.com/": "2026-05-17T10:00:00+00:00"}
    path.write_text(json.dumps(original_payload), encoding="utf-8")

    real_replace = Path.replace

    def boom(self: Path, target: Path) -> None:  # type: ignore[no-untyped-def]
        # Only blow up the wayback-history rename, not unrelated ones.
        if str(target).endswith("wayback-history.json"):
            raise OSError("disk full (simulated)")
        real_replace(self, target)

    monkeypatch.setattr(Path, "replace", boom)

    try:
        wayback_save.save_history(
            path,
            {"https://pursueindex.com/new": datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)},
        )
    except OSError:
        pass  # the simulated failure propagates; that's fine

    # Original file content must be untouched.
    assert json.loads(path.read_text(encoding="utf-8")) == original_payload


def test_load_history_recovers_from_corrupt_json(
    tmp_path: Path, capsys
) -> None:
    """M2 (Codex P2): unreadable JSON returns ``{}`` + emits a warning.

    A crashed write (pre-M1) could leave a half-serialized JSON behind.
    Wrapping json.loads in try/except means the next run starts from an
    empty history rather than crashing on the corrupt file.
    """
    path = tmp_path / "wayback-history.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = wayback_save.load_history(path)
    assert result == {}
    captured = capsys.readouterr()
    assert "::warning::" in captured.out
    assert "history" in captured.out.lower()


def test_load_history_returns_empty_for_missing_file(tmp_path: Path) -> None:
    """Sanity: load_history of a non-existent path returns ``{}``."""
    path = tmp_path / "absent.json"
    assert wayback_save.load_history(path) == {}


# --- DoS posture: --max-urls cap --------------------------------------


def test_apply_max_urls_cap_truncates_oversized_plan() -> None:
    """M-new: ``apply_max_urls_cap`` truncates the plan and emits a warning.

    A runaway sitemap (typo, infinite loop, attacker-controlled subdomain
    with a 1M-URL sitemap-index) must not pin the Wayback queue. The cap
    is a soft ceiling; truncation is reported via a GH Actions
    ``::warning::`` annotation so operators see it in the run summary.
    """
    urls = [f"https://pursueindex.com/p{i}" for i in range(1500)]
    capped, warning = wayback_save.apply_max_urls_cap(urls, max_urls=1000)
    assert len(capped) == 1000
    assert capped[0] == urls[0]
    assert capped[-1] == urls[999]
    assert warning is not None
    assert "1500" in warning and "1000" in warning


def test_apply_max_urls_cap_no_op_when_under_cap() -> None:
    """Plan size under the cap: passes through, no warning."""
    urls = [f"https://pursueindex.com/p{i}" for i in range(200)]
    capped, warning = wayback_save.apply_max_urls_cap(urls, max_urls=1000)
    assert capped == urls
    assert warning is None


def test_apply_max_urls_cap_no_op_when_exactly_at_cap() -> None:
    """Plan size == cap: passes through, no warning (off-by-one guard)."""
    urls = [f"https://pursueindex.com/p{i}" for i in range(1000)]
    capped, warning = wayback_save.apply_max_urls_cap(urls, max_urls=1000)
    assert capped == urls
    assert warning is None
