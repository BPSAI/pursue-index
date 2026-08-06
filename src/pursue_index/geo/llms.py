"""Pure builders + freshness check for the llms.txt discovery surfaces.

No I/O and no network — the script in ``scripts/build_llms_txt.py`` supplies
manifest rows and OCR excerpts, so every rule here is unit-testable.

Why this exists: `llms.txt` and `llms-full.txt` were hand-maintained, so a
tranche that added cards left them describing the previous release with nothing
to catch it. `check_geo_freshness` is the gate the ship path calls; the builders
are what makes passing it cheap.

Scope: a tranche changes cards, counts, and the manifest sha. It does not touch
the hand-written prose sections, nor the editorial `/finds` articles inlined in
`llms-full.txt`. `replace_section` therefore rewrites one named section and
leaves the rest of the document byte-identical.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SITE_ORIGIN = "https://pursueindex.com"

# Excerpts are cut at a fixed width; the intro paragraph quotes this number.
EXCERPT_CHARS = 500

# `> Manifest: 334 cards · csv_sha256 13e730c18d6ea586`
_PROVENANCE_PREFIX = "> Manifest:"
_PROVENANCE_RE = re.compile(
    r"^>\s*Manifest:\s*(?P<count>\d+)\s+cards?\s*·\s*csv_sha256\s+(?P<sha>[0-9a-f]+)\s*$",
    re.MULTILINE,
)


def build_provenance_line(*, card_count: int, csv_sha256: str) -> str:
    """The line that makes a generated document checkable against a manifest."""
    noun = "card" if card_count == 1 else "cards"
    return f"{_PROVENANCE_PREFIX} {card_count} {noun} · csv_sha256 {csv_sha256}"


def parse_provenance(document: str) -> tuple[int, str] | None:
    """``(card_count, csv_sha256)`` if the document carries provenance."""
    match = _PROVENANCE_RE.search(document)
    if match is None:
        return None
    return int(match.group("count")), match.group("sha")


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------


def _card_url(card: Mapping[str, Any]) -> str:
    return f"{SITE_ORIGIN}/card/{card['card_id']}"


def card_display_date(card: Mapping[str, Any]) -> str | None:
    """The date these surfaces show for a card.

    Precedence mirrors what the published files already contain: the curated
    overlay wins where an operator has reviewed the card, otherwise the CSV's
    incident date, otherwise the release date (72 cards carry no incident date
    at all). Derived from the published output rather than assumed — reading
    only ``display_date`` would silently drop the date from every card today,
    because the curation overlay is not yet populated.
    """
    return (
        card.get("display_date") or card.get("incident_date") or card.get("release_date")
    ) or None


def card_index_line(card: Mapping[str, Any]) -> str:
    """One line of the ``## Cards`` section in llms.txt."""
    agency = card.get("agency") or "Unknown agency"
    date = card_display_date(card)
    suffix = f"{agency} ({date})." if date else f"{agency}."
    return f"- [{card['card_id']} — {card['title']}]({_card_url(card)}): {suffix}"


def build_cards_intro(*, card_count: int) -> str:
    """Lead paragraph of llms-full.txt's ``## Cards``.

    Regenerated rather than preserved: the published copy hardcoded the card
    count, which is precisely the drift this task exists to remove.
    """
    return (
        f"{card_count} cards across the current corpus. Each card has a canonical "
        "URL on this site and a \n`sameAs` link back to its war.gov artifact. Where "
        "OCR text is available, the first page's text is included verbatim below "
        f"(truncated to ~{EXCERPT_CHARS} characters)."
    )


# `(?:(?!^###\s).)*?` rather than a bare `.*?`: under DOTALL a lazy dot still
# crosses `###` boundaries, so a card with no excerpt would match forward into a
# LATER card's excerpt and steal it. That silently reattributes primary-source
# text to the wrong document.
_EXCERPT_RE = re.compile(
    r"^###\s+(?P<card_id>[0-9a-f]{16})\s(?:(?!^###\s).)*?"
    r"^Excerpt \(page \d+\):\n\n(?P<text>(?:(?!^###\s).)*?)(?=\n\n###\s|\n\n##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def parse_existing_excerpts(document: str) -> dict[str, str]:
    """Recover already-published excerpts, keyed by card_id.

    Trailing newlines are structural and stripped; a trailing *space* is not —
    it can be the last character of a fixed-width cut and must round-trip.
    """
    return {
        m.group("card_id"): m.group("text").rstrip("\n")
        for m in _EXCERPT_RE.finditer(document)
    }


def should_include_excerpt(card: Mapping[str, Any], *, already_published: bool) -> bool:
    """Whether this card may carry a first-page excerpt at all.

    An A/V card's OCR directory holds the text of the *paired* document, not of
    the recording itself — so emitting it would caption a Gemini 7 audio card
    with an Apollo 11 debriefing. On a citable archive that is a factual error,
    not a cosmetic one, which is why the published file omits those cards.

    Conservative by construction: refresh whatever is already published (the
    operator's curation decision, and live OCR agrees with it on every card
    that has both), and only introduce an excerpt for a new card when it is a
    PDF — the one asset type whose OCR is unambiguously its own.
    """
    if already_published:
        return True
    return (card.get("asset_type") or "").upper() == "PDF"


def resolve_excerpt(
    card_id: str, *, live: str | None, published: Mapping[str, str]
) -> str | None:
    """Live OCR when available, otherwise whatever is already published.

    Regeneration must never be destructive. The OCR tier lives on the NAS and
    can be partially mounted — and image-only cards carry vision-pass text that
    may not be present at all on the machine running the generator. Preferring
    live text but falling back to published text means a thin mount refreshes
    what it can and leaves the rest intact, instead of deleting it.
    """
    return live or published.get(card_id) or None


def render_card_detail(card: Mapping[str, Any], *, excerpt: str | None) -> str:
    """One ``### <card_id>`` entry of the ``## Cards`` section in llms-full.txt.

    Fields absent from a row are omitted rather than rendered as ``None`` —
    video and withdrawn cards legitimately carry no ``asset_url``, and the OCR
    excerpt is unavailable on any machine without the NAS tier mounted.
    """
    lines = [f"### {card['card_id']} — {card['title']}", ""]

    if agency := card.get("agency"):
        lines.append(f"- Agency: {agency}")
    if date := card_display_date(card):
        lines.append(f"- Date: {date}")
    lines.append(f"- URL: {_card_url(card)}")
    if asset_url := card.get("asset_url"):
        lines.append(f"- Source: {asset_url}")
    if description := card.get("description"):
        lines.append(f"- Description: {description}")

    if excerpt:
        lines += ["", "Excerpt (page 1):", "", excerpt]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section replacement
# ---------------------------------------------------------------------------


def replace_section(document: str, heading: str, body: str) -> str:
    """Replace the body of the ``## <heading>`` section, preserving the rest.

    Bounded by the next ``## `` heading so the editorial content that follows
    (the inlined `/finds` articles, which use deeper ``### ``/``## `` headings
    inside their own bodies) is never absorbed.

    Raises rather than appending when the heading is absent: a silent append
    would reorder the document and hide a renamed section.
    """
    # `[ \t]*` rather than `\s*` before the newline: `\s*` is greedy across
    # newlines, so it swallows the blank line under the heading and the rebuilt
    # document grows one blank line per call (breaking idempotency).
    pattern = re.compile(
        rf"^(?P<head>##[ \t]+{re.escape(heading)}[ \t]*\n)(?P<body>.*?)(?P<tail>^##[ \t]+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(document)
    if match is None:
        raise ValueError(f"section '{heading}' not found — refusing to append blindly")

    return (
        document[: match.start()]
        + match.group("head")
        # strip("\n") not strip(): an OCR excerpt cut at a fixed width can
        # legitimately end on a space, and it may be the final line here.
        + f"\n{body.strip(chr(10))}\n\n"
        + match.group("tail")
        + document[match.end() :]
    )


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeoFreshness:
    ok: bool
    problems: list[str] = field(default_factory=list)


def check_geo_freshness(
    *, card_count: int, csv_sha256: str, documents: Mapping[str, str]
) -> GeoFreshness:
    """Fail the ship step when a discovery surface disagrees with the manifest.

    Checks every document and reports all problems, so one ship run surfaces the
    full set rather than one per re-run. A document with no provenance line at
    all is a failure, not a pass — an ungenerated file must not slip through by
    having nothing to compare against.
    """
    problems: list[str] = []

    for name, text in documents.items():
        parsed = parse_provenance(text)
        if parsed is None:
            problems.append(
                f"{name}: no provenance line — run the generator "
                f"(expected '{_PROVENANCE_PREFIX} <n> cards · csv_sha256 <sha>')"
            )
            continue

        found_count, found_sha = parsed
        if found_count != card_count:
            problems.append(
                f"{name}: card count {found_count} != manifest {card_count} — stale"
            )
        if found_sha != csv_sha256:
            problems.append(
                f"{name}: csv_sha256 {found_sha} != manifest {csv_sha256} — stale"
            )

    return GeoFreshness(ok=not problems, problems=problems)


def render_freshness_report(result: GeoFreshness) -> str:
    """Operator-facing summary for the ship step."""
    if result.ok:
        return "GEO discovery metadata is current (llms.txt / llms-full.txt)."
    return "\n".join(
        ["GEO discovery metadata is STALE — regenerate before shipping:"]
        + [f"  * {p}" for p in result.problems]
    )
