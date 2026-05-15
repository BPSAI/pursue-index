"""Release-gate AC: every alias `new_card_id` has a built card detail page.

Companion to `test_card_page_coverage.py`. That test asserts every card
in the current manifest has a built page; this one asserts every alias
destination does too. The worker's redirect lane (`/card/<old_id>` →
`/card/<new_id>`) is only useful if the destination exists in the build.

Why this matters separately: aliases can in principle point at card_ids
NOT in the current manifest (e.g., a card was renamed twice and the
intermediate id is no longer in latest.json). In that case the worker
redirects to a 404 — silent breakage. Catching this in CI prevents the
class of bug where an alias chain ends at a dead destination.

`operator_revoke` entries don't enter the test set (they're tombstones
that remove an alias from the resolved map — the worker won't redirect
on them).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_ALIASES = _REPO_ROOT / "data" / "card-aliases.json"
_DIST_CARD = _REPO_ROOT / "web" / "dist" / "card"
_MAX_HOPS = 8


def _resolve_alias_map() -> dict[str, str]:
    """Mirror of `tests/unit/test_finds_citations.py::_load_alias_map`.

    Later entries win per old_card_id; `operator_revoke` removes
    the alias entry entirely (tombstone semantics).
    """
    if not _ALIASES.exists():
        return {}
    data = json.loads(_ALIASES.read_text())
    out: dict[str, str] = {}
    for row in data.get("aliases", []):
        old_id = row.get("old_card_id")
        new_id = row.get("new_card_id")
        if not (old_id and new_id):
            continue
        if row.get("method") == "operator_revoke":
            out.pop(old_id, None)
            continue
        out[old_id] = new_id
    return out


def _terminal_destination(card_id: str, aliases: dict[str, str]) -> str:
    """Walk the alias chain to its terminal id. Bounded by _MAX_HOPS."""
    seen: set[str] = set()
    cur = card_id
    for _ in range(_MAX_HOPS):
        if cur in seen:
            return cur  # cycle defense — return the loop entry
        seen.add(cur)
        if cur not in aliases:
            return cur
        cur = aliases[cur]
    return cur


def test_every_alias_terminal_has_a_dist_page() -> None:
    """Each alias's terminal `new_card_id` must have a built page.

    Walks the chain through to its terminal id (handling multi-hop
    renames). The terminal is what `/card/<old_id>` ultimately
    redirects to; if no page exists there, the redirect ends at a 404.
    """
    if not _DIST_CARD.is_dir():
        pytest.skip("web/dist/card/ not present — run npm run build first")

    aliases = _resolve_alias_map()
    if not aliases:
        pytest.skip("no aliases configured")

    missing: list[tuple[str, str]] = []
    for old_id in sorted(aliases):
        terminal = _terminal_destination(old_id, aliases)
        page = _DIST_CARD / terminal / "index.html"
        if not page.is_file():
            missing.append((old_id, terminal))

    if missing:
        sample = ", ".join(f"{o}→{t}" for o, t in missing[:10])
        more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        pytest.fail(
            f"{len(missing)} alias chain(s) end at a card_id with no built "
            f"page (would 301→404 in prod): {sample}{more}"
        )


def test_alias_chain_acyclic() -> None:
    """No alias chain may visit the same id twice (cycle defense).

    Mirrors the worker's runtime guard so CI catches misconfigured
    chains before they hit prod.
    """
    aliases = _resolve_alias_map()
    cyclic: list[str] = []
    for start in aliases:
        seen: set[str] = set()
        cur = start
        for _ in range(_MAX_HOPS):
            if cur in seen:
                cyclic.append(start)
                break
            seen.add(cur)
            if cur not in aliases:
                break
            cur = aliases[cur]
    if cyclic:
        pytest.fail(f"cyclic alias chain(s) starting at: {cyclic[:10]}")
