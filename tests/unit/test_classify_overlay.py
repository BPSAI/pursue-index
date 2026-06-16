"""Tests for scripts/classify_overlay.py.

Pins the silent-overlay detector's net-new-vs-overlay classification: a release
promote that only archives brand-new asset_urls must NOT be flagged as a
same-URL-different-bytes overlay (the recurring false-fire), while a genuine
existing-URL/new-sha row still is.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package; import the module directly (mirrors test_ocr_metrics).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from classify_overlay import classify_overlay_rows  # noqa: E402


def _row(url: str, sha: str, card_id: str = "c") -> dict:
    return {"card_id": card_id, "asset_url": url, "byte_sha256": sha}


def test_net_new_urls_are_not_overlays() -> None:
    """The false-fire case: a promote appends rows for brand-new URLs only."""
    prior = [_row("https://w/a", "sha_a")]
    current = prior + [_row("https://w/b", "sha_b"), _row("https://w/c", "sha_c")]
    result = classify_overlay_rows(prior, current)
    assert result.overlays == []
    assert {r["asset_url"] for r in result.net_new} == {"https://w/b", "https://w/c"}
    assert result.is_overlay is False


def test_existing_url_new_sha_is_overlay() -> None:
    """The real threat: a stable URL reappears with different bytes."""
    prior = [_row("https://w/a", "sha_a")]
    current = prior + [_row("https://w/a", "sha_a_MUTATED")]
    result = classify_overlay_rows(prior, current)
    assert len(result.overlays) == 1
    assert result.overlays[0]["asset_url"] == "https://w/a"
    assert result.overlays[0]["byte_sha256"] == "sha_a_MUTATED"
    assert result.is_overlay is True
    assert result.net_new == []


def test_unchanged_rows_are_ignored() -> None:
    """Same url+sha already in prior → neither overlay nor net-new."""
    prior = [_row("https://w/a", "sha_a")]
    current = list(prior)  # no appends
    result = classify_overlay_rows(prior, current)
    assert result.overlays == []
    assert result.net_new == []


def test_mixed_promote_with_one_overlay() -> None:
    """A promote that adds new cards AND happens to carry one true overlay:
    only the overlay is flagged; the net-new rows are not."""
    prior = [_row("https://w/a", "sha_a"), _row("https://w/b", "sha_b")]
    current = prior + [
        _row("https://w/c", "sha_c"),          # net-new
        _row("https://w/d", "sha_d"),          # net-new
        _row("https://w/a", "sha_a_MUTATED"),  # overlay
    ]
    result = classify_overlay_rows(prior, current)
    assert [r["asset_url"] for r in result.overlays] == ["https://w/a"]
    assert {r["asset_url"] for r in result.net_new} == {"https://w/c", "https://w/d"}
    assert result.is_overlay is True


def test_empty_prior_first_run_all_net_new() -> None:
    """Bootstrap: empty prior registry → everything is net-new, no overlay."""
    current = [_row("https://w/a", "sha_a"), _row("https://w/b", "sha_b")]
    result = classify_overlay_rows([], current)
    assert result.overlays == []
    assert len(result.net_new) == 2
