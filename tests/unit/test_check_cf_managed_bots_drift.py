"""Tests for ``scripts/check_cf_managed_bots_drift.py``.

Covers the pure parsing + diff helpers without any network I/O. The
script's ``main()`` is the only network-touching path and is exercised
manually via the weekly cron job (and operator dispatch); the helpers
below carry the meaningful logic.

CF Managed drift detection — if
Cloudflare expands the upstream Managed bot list, our hardcoded
``CF_MANAGED_BOTS`` const drifts and the rendered robots.txt either
duplicates lines (CF added a bot) or silently omits them (CF removed
one).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_cf_managed_bots_drift as drift  # noqa: E402


# --- live-block extraction -------------------------------------------


_LIVE_ROBOTS_TXT = """
User-agent: *
Allow: /
Content-Signal: search=yes,ai-train=no

# BEGIN Cloudflare Managed content
User-agent: Amazonbot
Disallow: /

User-agent: Bytespider
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: meta-externalagent
Disallow: /
# END Cloudflare Managed Content

User-agent: PanguBot
Disallow: /
""".strip()


def test_extract_cf_block_returns_section_between_sentinels() -> None:
    """The CF Managed slice is the body between BEGIN/END markers."""
    block = drift.extract_cf_block(_LIVE_ROBOTS_TXT)
    assert "User-agent: Amazonbot" in block
    assert "User-agent: meta-externalagent" in block
    # The PanguBot block (post-END) is NOT part of the CF Managed slice.
    assert "User-agent: PanguBot" not in block


def test_extract_cf_block_returns_empty_when_no_sentinel() -> None:
    """A robots.txt without the CF Managed markers yields an empty slice.

    This is the "CF Managed disabled" case — the script must short-
    circuit cleanly rather than crash.
    """
    body = "User-agent: *\nAllow: /\n"
    assert drift.extract_cf_block(body) == ""


# --- user-agent parsing ----------------------------------------------


def test_parse_user_agents_strips_whitespace_and_skips_wildcard() -> None:
    block = "User-agent: Amazonbot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    agents = drift.parse_user_agents(block)
    assert agents == ["Amazonbot"]


def test_parse_user_agents_handles_multiple_entries() -> None:
    block = drift.extract_cf_block(_LIVE_ROBOTS_TXT)
    agents = drift.parse_user_agents(block)
    assert agents == [
        "Amazonbot",
        "Bytespider",
        "ClaudeBot",
        "meta-externalagent",
    ]


# --- const parsing ---------------------------------------------------


_FAKE_ROBOTS_TS = """
export const CF_MANAGED_BOTS: readonly string[] = [
  "Amazonbot",
  "Applebot-Extended",
  "Bytespider",
  // inline comment
  "ClaudeBot",
  "meta-externalagent",  // lowercased by CF
] as const;
""".strip()


def test_parse_const_list_returns_literal_members() -> None:
    """The TS const array yields exactly its string-literal members."""
    bots = drift.parse_const_list(_FAKE_ROBOTS_TS)
    assert bots == [
        "Amazonbot",
        "Applebot-Extended",
        "Bytespider",
        "ClaudeBot",
        "meta-externalagent",
    ]


def test_parse_const_list_raises_when_const_missing() -> None:
    """If the const is renamed or removed, the script raises explicitly."""
    import pytest

    with pytest.raises(ValueError, match="CF_MANAGED_BOTS const not found"):
        drift.parse_const_list("export const SOMETHING_ELSE = []")


# --- diff ------------------------------------------------------------


def test_diff_bot_lists_no_drift() -> None:
    """Same-set inputs yield empty diffs."""
    only_live, only_const = drift.diff_bot_lists(
        ["GPTBot", "ClaudeBot"], ["GPTBot", "ClaudeBot"]
    )
    assert only_live == []
    assert only_const == []


def test_diff_bot_lists_case_insensitive() -> None:
    """CF lowercases ``meta-externalagent``; our const preserves CamelCase."""
    only_live, only_const = drift.diff_bot_lists(
        ["meta-externalagent"], ["Meta-ExternalAgent"]
    )
    assert only_live == []
    assert only_const == []


def test_diff_bot_lists_detects_new_in_live() -> None:
    """CF added a bot upstream that we don't list in the const."""
    only_live, only_const = drift.diff_bot_lists(
        ["GPTBot", "NewBot", "ClaudeBot"], ["GPTBot", "ClaudeBot"]
    )
    assert only_live == ["NewBot"]
    assert only_const == []


def test_diff_bot_lists_detects_dropped_from_live() -> None:
    """CF removed a bot upstream; our const still lists it (silent hole)."""
    only_live, only_const = drift.diff_bot_lists(
        ["GPTBot"], ["GPTBot", "OldBot"]
    )
    assert only_live == []
    assert only_const == ["OldBot"]


def test_diff_bot_lists_reports_both_directions() -> None:
    """Mixed drift: one added upstream + one dropped upstream."""
    only_live, only_const = drift.diff_bot_lists(
        ["GPTBot", "NewBot"], ["GPTBot", "OldBot"]
    )
    assert only_live == ["NewBot"]
    assert only_const == ["OldBot"]


# --- end-to-end const parse against the real robots.ts --------------


def test_const_parse_matches_real_robots_ts() -> None:
    """The parser must succeed against the actual checked-in robots.ts."""
    robots_ts = _REPO_ROOT / "web" / "src" / "lib" / "robots.ts"
    text = robots_ts.read_text(encoding="utf-8")
    bots = drift.parse_const_list(text)
    # Sanity: at least the canonical pre-Sprint-4a entries must parse.
    assert "Amazonbot" in bots
    assert "Bytespider" in bots
    assert "ClaudeBot" in bots
    assert "GPTBot" in bots
    assert "meta-externalagent" in bots
