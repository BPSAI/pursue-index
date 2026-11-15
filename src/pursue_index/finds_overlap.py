"""Cross-entry overlap gate for the `/finds` corpus.

Companion to `finds_validator`'s single-entry structural check. Two
entries that cite the same card (declare it in their frontmatter
`cards:` list) are expected to cross-reference each other — a reader
who lands on one should be pointed at the other — unless one entry
explicitly declares itself a `supplements:` follow-up to the other.
An entry citing a card another entry already covers, with no link and
no `supplements:` declaration, is a silent editorial gap: this module
is the gate that catches it.

Used by `finds_validator.main()` (the CLI / release-gate path) and by
`tests/unit/test_finds_validator.py` (fixture tests plus a full-corpus
integration test).
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from pursue_index.finds_frontmatter import body_text as _body_text
from pursue_index.finds_frontmatter import extract_frontmatter as _extract_frontmatter

_FINDS_BODY_LINK = re.compile(r"\]\(/finds/([a-zA-Z0-9][a-zA-Z0-9_-]*)\)")


class _StringLoader(yaml.SafeLoader):
    """SafeLoader that keeps numbers and dates as the strings they were written as.

    Astro's schema (``web/src/content.config.ts``) types ``cards`` and
    ``supplements`` as strings. A card id written without quotes that happens
    to be all digits must not become an integer and lose its leading zeros.
    """


_StringLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers
            if tag not in ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float",
                           "tag:yaml.org,2002:timestamp")]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _frontmatter(text: str) -> dict[str, Any]:
    """The entry's frontmatter as a mapping; raises ``yaml.YAMLError`` if invalid."""
    block = _extract_frontmatter(text)
    # _StringLoader is a SafeLoader subclass, so this builds no Python objects.
    data = yaml.load(block, Loader=_StringLoader) if block else None
    return data if isinstance(data, dict) else {}


def _frontmatter_cards(fm: dict[str, Any]) -> list[str]:
    """Card ids in the frontmatter ``cards:`` list, in either YAML list form."""
    cards = fm.get("cards")
    return [c.strip() for c in cards if isinstance(c, str) and c.strip()] if isinstance(cards, list) else []


def _frontmatter_supplements(fm: dict[str, Any]) -> str | None:
    """The slug named by a ``supplements:`` frontmatter field, if present."""
    value = fm.get("supplements")
    return value.strip() or None if isinstance(value, str) else None


def _body_finds_links(body: str) -> set[str]:
    """Slugs targeted by `[...](/finds/<slug>)` links in the body."""
    return set(_FINDS_BODY_LINK.findall(body))


def check_finds_overlap(entries: dict[str, str]) -> list[str]:
    """Cross-entry overlap gate for a `/finds` corpus.

    ``entries`` maps slug -> raw `.mdx` text. Two entries that cite the
    same card must link each other in the body — a link in either
    direction is sufficient — or one must declare `supplements:` naming
    the other. A `supplements:` value that does not name a known slug
    is also an error.

    A `supplements:` value naming the entry itself is also an error.

    Returns a list of error strings, each naming the offending pair and
    the shared card id(s), or the bad `supplements:` reference.
    """
    errors: list[str] = []
    parsed = {}
    for slug, text in entries.items():
        try:
            fm = _frontmatter(text)
        except yaml.YAMLError as exc:
            errors.append(f"'{slug}' frontmatter is not valid YAML: {exc}".splitlines()[0])
            fm = {}
        parsed[slug] = {
            "cards": _frontmatter_cards(fm),
            "links": _body_finds_links(_body_text(text)),
            "supplements": _frontmatter_supplements(fm),
        }

    for slug, info in sorted(parsed.items()):
        supplements = info["supplements"]
        if supplements is not None and supplements == slug:
            errors.append(f"'{slug}' declares supplements: itself, which names no other entry")
        elif supplements is not None and supplements not in parsed:
            errors.append(
                f"'{slug}' declares supplements: '{supplements}', "
                "which is not a known /finds entry"
            )

    pair_cards: dict[tuple[str, str], list[str]] = {}
    card_to_slugs: dict[str, list[str]] = {}
    for slug, info in parsed.items():
        for card in info["cards"]:
            card_to_slugs.setdefault(card, []).append(slug)
    for card, slugs in card_to_slugs.items():
        unique_slugs = sorted(set(slugs))
        for i in range(len(unique_slugs)):
            for j in range(i + 1, len(unique_slugs)):
                pair = (unique_slugs[i], unique_slugs[j])
                pair_cards.setdefault(pair, []).append(card)

    for (a, b), cards in sorted(pair_cards.items()):
        a_info, b_info = parsed[a], parsed[b]
        linked = b in a_info["links"] or a in b_info["links"]
        supplemented = a_info["supplements"] == b or b_info["supplements"] == a
        if linked or supplemented:
            continue
        card_list = ", ".join(sorted(cards))
        errors.append(
            f"'{a}' and '{b}' both cite card(s) {card_list} with no link between "
            "them and no `supplements:` declaration naming the other"
        )

    return errors
