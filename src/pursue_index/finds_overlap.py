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

from pursue_index.finds_frontmatter import body_text as _body_text
from pursue_index.finds_frontmatter import extract_frontmatter as _extract_frontmatter

_SUPPLEMENTS_FIELD = re.compile(r'^supplements:[ \t]*"?([^"\n]+?)"?[ \t]*$', re.MULTILINE)
_FINDS_BODY_LINK = re.compile(r"\]\(/finds/([a-zA-Z0-9][a-zA-Z0-9_-]*)\)")


def _frontmatter_cards(fm_text: str) -> list[str]:
    """Card ids in the frontmatter `cards:` list, quotes stripped.

    Line-based rather than a single block regex, so it doesn't depend
    on `cards:` being followed by a trailing newline — true for every
    real entry (there's always a later field) but not guaranteed for a
    minimal fixture where `cards:` is the last frontmatter line.
    """
    cards: list[str] = []
    in_cards = False
    for line in fm_text.splitlines():
        if not in_cards:
            if re.match(r"^cards:\s*$", line):
                in_cards = True
            continue
        if line.strip() == "":
            continue
        if line[0].isspace() and line.strip().startswith("-"):
            item = line.strip()[1:].strip().strip('"').strip("'")
            cards.append(item)
        else:
            break
    return cards


def _frontmatter_supplements(fm_text: str) -> str | None:
    """The slug named by a `supplements:` frontmatter field, if present."""
    m = _SUPPLEMENTS_FIELD.search(fm_text)
    return m.group(1).strip() if m else None


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

    Returns a list of error strings, each naming the offending pair and
    the shared card id(s), or the bad `supplements:` reference.
    """
    parsed = {
        slug: {
            "cards": _frontmatter_cards(_extract_frontmatter(text) or ""),
            "links": _body_finds_links(_body_text(text)),
            "supplements": _frontmatter_supplements(_extract_frontmatter(text) or ""),
        }
        for slug, text in entries.items()
    }

    errors: list[str] = []

    for slug, info in sorted(parsed.items()):
        supplements = info["supplements"]
        if supplements is not None and supplements not in parsed:
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
