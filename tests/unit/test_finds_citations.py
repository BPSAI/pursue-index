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

import html
import json
import re
from pathlib import Path

import pytest

from pursue_index.release.chunked_asset import read_asset_json

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


# ---------------------------------------------------------------------------
# page and q: a reader can check the citation against the published text
# ---------------------------------------------------------------------------
# One <Cite .../> tag; its attributes are read separately so their order is free.
CITE_TAG = re.compile(r"<Cite\s([^>]*?)/?>", re.DOTALL)
QUOTE_BASELINE = _REPO_ROOT / "tests" / "fixtures" / "finds-quote-baseline.json"


def _attr(attrs: str, name: str) -> str | None:
    hit = re.search(rf"\b{name}=(?:\{{(\d+)\}}|\"([^\"]*)\"|'([^']*)')", attrs)
    return next((g for g in hit.groups() if g is not None), None) if hit else None


def _norm(text: str) -> str:
    """The match rule: whitespace runs collapse to one space, case is ignored
    (the card page highlights q case-insensitively), and HTML entities in an
    MDX attribute are read as the characters they stand for."""
    return re.sub(r"\s+", " ", html.unescape(text)).strip().casefold()


def _cites(name: str, mdx_text: str) -> list[tuple[str, str, int, str | None]]:
    out = []
    for tag in CITE_TAG.finditer(mdx_text):
        card, page = _attr(tag.group(1), "card"), _attr(tag.group(1), "page")
        if card and page and page.isdigit():
            out.append((name, card, int(page), _attr(tag.group(1), "q")))
    return out


def _published_pages() -> dict[str, dict[int, list[str]]]:
    """{card_id: {page: [OCR text, cleaned text]}}, normalised, from the payloads
    the site ships."""
    pages: dict[str, dict[int, list[str]]] = {}
    data = _REPO_ROOT / "web" / "public" / "data"
    for row in read_asset_json(data / "pages.json"):
        pages.setdefault(row["card_id"], {}).setdefault(row["page"], []).append(_norm(row["text"]))
    for row in read_asset_json(data / "pages-cleaned.json")["pages"]:
        pages.setdefault(row["card_id"], {}).setdefault(row["page"], []).append(_norm(row["text"]))
    return pages


def quote_problems(cites: list[tuple[str, str, int, str | None]],
                   pages: dict[str, dict[int, list[str]]],
                   aliases: dict[str, str]) -> list[dict[str, object]]:
    """Each citation whose page is outside its card's pages, or whose q is not
    in that page's OCR or cleaned text. Cards with no published pages (removed
    cards) are left to the resolvability test above."""
    problems: list[dict[str, object]] = []
    for name, card, page, q in cites:
        card_pages = pages.get(_resolve_card(card, aliases))
        if card_pages is None:
            continue
        if page not in card_pages:
            problem = f"page {page} is outside the card's pages 1-{max(card_pages)}"
        elif q and not any(_norm(q) in text for text in card_pages[page]):
            problem = "q is not in the page's OCR or cleaned text"
        else:
            continue
        problems.append({"file": name, "card": card, "page": page, "q": q, "problem": problem})
    return problems


def _corpus_problems() -> list[dict[str, object]]:
    cites = [c for path in _all_finds_files() for c in _cites(path.name, path.read_text())]
    return quote_problems(cites, _published_pages(), _load_alias_map())


def _key(row: dict[str, object]) -> tuple[object, ...]:
    return (row["file"], row["card"], row["page"], row["q"])


def test_every_cited_page_and_quote_is_in_the_published_text() -> None:
    """New citations must check out. The baseline lists the reviewed ones that
    don't yet, with why; it may only shrink, so a fixed entry must leave it."""
    baseline = {_key(r): r for r in json.loads(QUOTE_BASELINE.read_text())["entries"]}
    found = {_key(r): r for r in _corpus_problems()}
    new = [found[k] for k in found.keys() - baseline.keys()]
    fixed = [baseline[k] for k in baseline.keys() - found.keys()]
    msg = []
    if new:
        msg.append("Citations whose page or q is not in the published text:\n  " + "\n  ".join(
            f"{r['file']}: card {r['card']} page {r['page']} q={r['q']!r}: {r['problem']}" for r in new))
    if fixed:
        msg.append(f"These now check out; remove them from {QUOTE_BASELINE.name}:\n  " + "\n  ".join(
            f"{r['file']}: card {r['card']} page {r['page']} q={r['q']!r}" for r in fixed))
    assert not msg, "\n\n".join(msg)


_FIXTURE_PAGES = {"a" * 16: {1: [_norm("The object was\n  SILVER and round.")], 2: [_norm("page two")]}}


def test_a_q_not_on_the_cited_page_fails() -> None:
    cites = [("x.mdx", "a" * 16, 1, "gold and round"), ("x.mdx", "a" * 16, 2, "silver")]
    assert [r["problem"] for r in quote_problems(cites, _FIXTURE_PAGES, {})] == [
        "q is not in the page's OCR or cleaned text"] * 2


def test_a_page_past_the_cards_last_page_fails() -> None:
    problems = quote_problems([("x.mdx", "a" * 16, 3, None)], _FIXTURE_PAGES, {})
    assert problems[0]["problem"] == "page 3 is outside the card's pages 1-2"


def test_q_matches_across_whitespace_case_and_entities() -> None:
    cites = [("x.mdx", "a" * 16, 1, "object was silver"), ("x.mdx", "a" * 16, 1, "the  object&#32;was")]
    assert quote_problems(cites, _FIXTURE_PAGES, {}) == []


def test_an_aliased_card_is_checked_against_its_new_pages() -> None:
    cites = [("x.mdx", "b" * 16, 1, "silver")]
    assert quote_problems(cites, _FIXTURE_PAGES, {"b" * 16: "a" * 16}) == []


def test_cite_tags_are_parsed_in_any_attribute_order() -> None:
    text = '<Cite q="silver" page={2} card="aaaaaaaaaaaaaaaa" />\n<Cite card=\'bbbbbbbbbbbbbbbb\' page={1} />'
    assert _cites("x.mdx", text) == [("x.mdx", "a" * 16, 2, "silver"), ("x.mdx", "b" * 16, 1, None)]

