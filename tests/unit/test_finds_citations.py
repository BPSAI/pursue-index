"""CI test: every <Cite card="..."> in /finds resolves.

A finds entry citing a card_id that no longer exists in the deployed
manifest (and isn't reachable via the alias chain) is a silent
breakage — the reader follows a link, gets a 404, the editorial
credibility takes a hit. Catch this in CI rather than discovering it
post-deploy.

The test walks every `.mdx` in `web/src/content/finds/` and for each
`<Cite card="<id>">` (plus the `cards:` frontmatter list) asserts the
card_id resolves to a card in the current manifest, either directly
or via `data/card-aliases.json`. Alias chains are followed up to a
reasonable depth (any rename → re-rename → re-re-rename ladder is
walked transitively).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CITE_PATTERN = re.compile(r'<Cite\s+card=["\']([a-f0-9]{16})["\']')
FRONTMATTER_CARDS_PATTERN = re.compile(
    r"^cards:\s*\n((?:\s*-\s*[a-f0-9]{16}\s*\n)+)", re.MULTILINE
)
CARD_ID_INLINE = re.compile(r"^\s*-\s*([a-f0-9]{16})", re.MULTILINE)
_MAX_ALIAS_HOPS = 8


def _load_manifest_card_ids() -> set[str]:
    path = _REPO_ROOT / "data" / "manifests" / "latest.json"
    data = json.loads(path.read_text())
    return {c["card_id"] for c in data["cards"]}


def _load_removed_card_ids() -> set[str]:
    path = _REPO_ROOT / "web" / "public" / "data" / "removed-cards.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return {entry["card"]["card_id"] for entry in data.get("removed", [])}


def _load_alias_map() -> dict[str, str]:
    """Build {old_card_id: new_card_id} honoring append-only semantics.

    Mirrors the worker's logic: later entries win per old_card_id;
    `method: operator_revoke` removes the alias entry entirely.
    """
    path = _REPO_ROOT / "data" / "card-aliases.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
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


def _resolve_card(card_id: str, aliases: dict[str, str]) -> str:
    """Follow the alias chain to the terminal card_id (or return the
    original if no alias applies). Bounded by _MAX_ALIAS_HOPS to
    prevent runaway in a misconfigured chain.
    """
    visited: set[str] = set()
    current = card_id
    for _ in range(_MAX_ALIAS_HOPS):
        if current in visited:
            break  # cycle defense
        visited.add(current)
        if current not in aliases:
            return current
        current = aliases[current]
    return current


def _extract_cite_card_ids(mdx_text: str) -> set[str]:
    cite_hits = set(CITE_PATTERN.findall(mdx_text))
    frontmatter_block = FRONTMATTER_CARDS_PATTERN.search(mdx_text)
    if frontmatter_block:
        cite_hits.update(CARD_ID_INLINE.findall(frontmatter_block.group(1)))
    return cite_hits


def _all_finds_files() -> list[Path]:
    finds_dir = _REPO_ROOT / "web" / "src" / "content" / "finds"
    return sorted(finds_dir.glob("*.mdx"))


def test_finds_citations_resolve_via_manifest_or_alias() -> None:
    manifest_ids = _load_manifest_card_ids()
    removed_ids = _load_removed_card_ids()
    aliases = _load_alias_map()
    valid_terminals = manifest_ids | removed_ids

    failures: list[str] = []
    for path in _all_finds_files():
        text = path.read_text()
        for card_id in sorted(_extract_cite_card_ids(text)):
            resolved = _resolve_card(card_id, aliases)
            if resolved not in valid_terminals:
                failures.append(
                    f"{path.name}: card_id `{card_id}` "
                    f"(resolves to `{resolved}`) — not in manifest, "
                    f"not in /removed, not aliased to either"
                )
    if failures:
        msg = "Unresolvable finds citations:\n  " + "\n  ".join(failures)
        pytest.fail(msg)


def test_alias_chain_is_acyclic() -> None:
    """An alias chain that loops back to its own old_card_id is a
    misconfiguration that would wedge the worker resolver into a
    redirect loop. Assert no cycles exist among current aliases."""
    aliases = _load_alias_map()
    for old_id in aliases:
        seen: set[str] = set()
        current = old_id
        for _ in range(_MAX_ALIAS_HOPS):
            if current in seen:
                pytest.fail(f"alias cycle detected starting at {old_id}: {' → '.join(seen)} → {current}")
            seen.add(current)
            if current not in aliases:
                break
            current = aliases[current]


def test_finds_citation_count_baseline_nonzero() -> None:
    """Sanity: at least the apollo-17.mdx entry should yield citation hits.
    If this returns 0 the extraction regex is broken."""
    target = _REPO_ROOT / "web" / "src" / "content" / "finds" / "apollo-17.mdx"
    if not target.exists():
        pytest.skip("apollo-17.mdx not present; skipping baseline")
    text = target.read_text()
    hits = _extract_cite_card_ids(text)
    assert len(hits) > 0, "extraction regex matched zero <Cite> entries in apollo-17.mdx"
