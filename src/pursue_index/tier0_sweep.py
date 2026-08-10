"""Tier-0 sweep of the government's own CSV descriptions (spec §5, PV1.2).

The releasing agency's description field is the highest-authority provenance
source available, and it is already ingested in every manifest. When war.gov's
own wording concedes that a file was previously posted, released, published or
declassified, that concession *outranks every other source* — no Wayback
lookup, no byte match, no external mirror can be more authoritative than the
publisher admitting it itself. And it is free: this sweep runs before anything
is fetched or built.

So this stage reads ``data/manifests/latest.json`` and, for every card whose
description **asserts** a prior release, FOIA history or declassification,
emits a :class:`Tier0Claim`. The claim reuses the :class:`ProvenanceTier`
taxonomy from PV1.1 and preserves the government's wording *verbatim* as its
evidence — never paraphrased.

Two deliberate restraints, both flowing from PV1.1's doctrine:

* **Precision over recall.** A description that merely contains a word like
  "released" (in "never before released") or "previously" (in "previously
  observed") does not produce a claim. The detectors key on specific
  prior-release phrasings, not on lone keywords.
* **No forged dates.** A full :class:`~pursue_index.provenance.ProvenanceClaim`
  needs an establishing date, an artifact URL and a ``date_basis``; a bare CSV
  description rarely supplies the prior copy's URL or capture date. Rather than
  fabricate them, a Tier-0 claim records only what the government actually
  stated: the tier, the verbatim admission, the named prior source, and a date
  *only when the description states a full calendar date*. Later pipeline
  stages resolve these leads into fully-evidenced ``ProvenanceClaim``s.

Pure text + (de)serialisation over an already-loaded manifest, plus a thin
``main`` that writes the tracked artifact. Regexes match on the raw text with
``\\s+`` gaps, so non-breaking spaces (U+00A0, which war.gov uses freely) are
absorbed without disturbing the verbatim evidence spans.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

from pursue_index.provenance import (
    POSITIVE_TIERS,
    DateBasis,
    ProvenanceTier,
    is_citable_prior_source,
)

__all__ = [
    "OUTPUT_PATH",
    "SweepResult",
    "Tier0Claim",
    "build_output",
    "detect_claim",
    "sweep",
    "sweep_file",
]

#: Tracked output artifact (under ``data/``, never an ignored directory).
OUTPUT_PATH = Path("data") / "provenance" / "tier0-manifest-claims.json"

_SCHEMA = "tier0-manifest-provenance/v1"
_SOURCE = "war.gov CSV manifest description"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_DATE_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})")

#: Why a matched rule can yield no claim — published beside the count.
UNCITABLE_PRIOR_SOURCE_REASON = (
    "No claim: the description asserts a prior release but the source it names "
    "is not an address a reader can follow, and a Tier-0 claim is published as "
    "a pointer to that source. Naming a different source from a weaker rule "
    "would attribute the release to something the description did not say."
)


@dataclass(frozen=True)
class Tier0Claim:
    """A dated-when-stated, sourced prior-release claim read from the CSV.

    It carries a positive :class:`ProvenanceTier`, the verbatim government
    wording that backs it (``evidence``, always an exact substring of the
    card description), and the named prior source the government pointed to.
    ``stated_date``/``date_basis`` are populated only when the description
    states a full calendar date; they travel together or not at all.
    """

    card_id: str
    identifier: str
    title: str
    tier: ProvenanceTier
    evidence: str
    prior_source: str
    source: str = _SOURCE
    stated_date: date | None = None
    date_basis: DateBasis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tier, ProvenanceTier):
            raise TypeError(f"tier must be a ProvenanceTier, got {self.tier!r}")
        if self.tier not in POSITIVE_TIERS:
            raise ValueError(
                f"a Tier-0 claim is a positive assertion; tier {self.tier.value!r} "
                "cannot be used ('no_prior_release_found' is not a Tier-0 outcome)"
            )
        for name in ("card_id", "identifier", "evidence", "prior_source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"a Tier-0 claim requires non-blank {name}")
        if not is_citable_prior_source(self.prior_source):
            raise ValueError(
                "prior_source is published as the pointer a reader is given, so it "
                "must be an outlet name, a bare domain or an absolute http(s) URL; "
                f"{self.prior_source!r} is none of those"
            )
        if (self.stated_date is None) != (self.date_basis is None):
            raise ValueError("stated_date and date_basis must be set together or not at all")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "tier0_manifest_claim",
            "card_id": self.card_id,
            "identifier": self.identifier,
            "title": self.title,
            "tier": self.tier.value,
            "evidence": self.evidence,
            "prior_source": self.prior_source,
            "source": self.source,
            "stated_date": self.stated_date.isoformat() if self.stated_date else None,
            "date_basis": self.date_basis.value if self.date_basis else None,
        }


class _Rule(NamedTuple):
    """One prior-release phrasing and the claim it produces when matched."""

    name: str
    pattern: re.Pattern[str]
    tier: ProvenanceTier
    prior_source: str | None  # static label, or None to read a capture group
    prior_source_group: int | None
    date_group: int | None


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Ordered most-specific first; the first matching rule wins for a card. Each
# regex targets a concrete prior-release assertion, never a lone keyword.
_RULES: tuple[_Rule, ...] = (
    # FBI 62-HQ-83894: "partially posted on FBI vault ... some pages missing".
    _Rule("fbi_vault_partial",
          _c(r"partially\s+posted\s+on[^.]*?\bvault\b"),
          ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART, "FBI Vault", None, None),
    # Pantex: pages "originally released ... in a more redacted form on <date>".
    _Rule("originally_released_redacted",
          _c(r"originally\s+released\b[^.]*?more\s+redacted\s+form\s+on\s+"
             r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})"),
          ProvenanceTier.PREVIOUSLY_RELEASED_IN_PART, "prior PURSUE release", None, 1),
    # ODNI imagery: "originally released on <domain> on <date>".
    _Rule("originally_released_dated",
          _c(r"originally\s+released\s+on\s+(\S+)\s+on\s+"
             r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})"),
          ProvenanceTier.PREVIOUSLY_RELEASED, None, 1, 2),
    # COMETA: "previously published in <outlet> in <year>" (year only, no date).
    _Rule("previously_published",
          _c(r"previously\s+published\s+in\s+([^.)]+?)\s+in\s+\d{4}"),
          ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED, None, 1, None),
    # Apollo photo: "previously released" (distinct from "never before released").
    _Rule("previously_released",
          _c(r"previously\s+released"),
          ProvenanceTier.PREVIOUSLY_RELEASED, "prior public release", None, None),
    # CIA-019: "released by the National Archives ...".
    _Rule("released_by_archive",
          _c(r"released\s+by\s+(the\s+National\s+Archives[^.]*)"),
          ProvenanceTier.PREVIOUSLY_RELEASED, None, 1, None),
)


def _sentence_containing(text: str, start: int, end: int) -> str:
    """Return the verbatim sentence of ``text`` spanning ``[start, end)``."""
    terminators = ".!?\n"
    left = 0
    for i in range(start - 1, -1, -1):
        if text[i] in terminators:
            left = i + 1
            break
    right = len(text)
    for i in range(end, len(text)):
        if text[i] in terminators:
            right = i + 1
            break
    return text[left:right].strip()


def _parse_stated_date(text: str) -> date | None:
    """Parse a ``Month DD, YYYY`` calendar date, or ``None`` if absent."""
    match = _DATE_RE.search(text)
    if not match:
        return None
    month = _MONTHS.get(match.group(1).lower())
    if month is None:
        return None
    return date(int(match.group(3)), month, int(match.group(2)))


def _prior_source(rule: _Rule, match: re.Match[str]) -> str | None:
    """The prior source this match names, or ``None`` if it names no address.

    A rule either carries a static label or reads one out of the description. A
    captured token has to be something a reader can follow to be published as
    the prior source, so one that is not yields ``None`` — and the caller emits
    no claim rather than a claim pointing somewhere unreachable.
    """
    if rule.prior_source_group is None:
        return rule.prior_source
    captured = match.group(rule.prior_source_group).strip()
    return captured if is_citable_prior_source(captured) else None


def _first_match(description: str) -> tuple[_Rule, re.Match[str]] | None:
    """The most specific prior-release phrasing this description asserts.

    ``_RULES`` runs most-specific first, so the first hit is the card's reading:
    it fixes both the tier and the source the government pointed at. That makes
    it the *only* reading — a later rule describes a different assertion, and
    pairing its tier with this card would state something the description does
    not.
    """
    for rule in _RULES:
        match = rule.pattern.search(description)
        if match is not None:
            return rule, match
    return None


def _claim_from(
    card: dict[str, Any], rule: _Rule, match: re.Match[str], prior_source: str
) -> Tier0Claim:
    """Build the claim a matched rule establishes, evidence kept verbatim."""
    description = card.get("description") or ""
    stated_date = _parse_stated_date(match.group(0)) if rule.date_group else None
    return Tier0Claim(
        card_id=str(card.get("card_id") or card.get("title") or ""),
        identifier=str(card.get("asset_filename") or card.get("title") or card.get("card_id") or ""),
        title=str(card.get("title") or ""),
        tier=rule.tier,
        evidence=_sentence_containing(description, match.start(), match.end()),
        prior_source=prior_source,
        stated_date=stated_date,
        date_basis=DateBasis.PUBLISHER_DATE if stated_date else None,
    )


class _Detection(NamedTuple):
    """One card's outcome: its claim, or the fact that its source was unnamed."""

    claim: Tier0Claim | None
    uncitable_prior_source: bool


def _detect(card: dict[str, Any]) -> _Detection:
    """Read one card: the claim it asserts, or why it asserts none."""
    description = card.get("description") or ""
    if not description.strip():
        return _Detection(None, False)
    found = _first_match(description)
    if found is None:
        return _Detection(None, False)
    rule, match = found
    prior_source = _prior_source(rule, match)
    if prior_source is None:
        return _Detection(None, True)
    return _Detection(_claim_from(card, rule, match, prior_source), False)


def detect_claim(card: dict[str, Any]) -> Tier0Claim | None:
    """Return the Tier-0 claim a card's description asserts, or ``None``.

    Precision over recall: only a concrete prior-release / declassification
    assertion yields a claim, and only when the source it names is one a reader
    can follow. The first matching rule is the card's reading.
    """
    return _detect(card).claim


class SweepResult(NamedTuple):
    """One pass over a manifest: the claims, and the cards left without one.

    ``uncitable_prior_source`` counts the cards whose description does assert a
    prior release but names a source no reader can follow. They carry no claim,
    and the count travels with the claims so the artifact says how many cards
    are in that position.
    """

    claims: list[Tier0Claim]
    uncitable_prior_source: int


def sweep(manifest: dict[str, Any]) -> SweepResult:
    """Emit a Tier-0 claim for every card whose description asserts one."""
    claims: list[Tier0Claim] = []
    uncitable = 0
    for card in manifest.get("cards", []):
        detection = _detect(card)
        if detection.claim is not None:
            claims.append(detection.claim)
        uncitable += int(detection.uncitable_prior_source)
    return SweepResult(claims, uncitable)


def sweep_file(path: Path) -> SweepResult:
    """Load a manifest JSON file and sweep it."""
    return sweep(json.loads(Path(path).read_text()))


def build_output(manifest: dict[str, Any], result: SweepResult) -> dict[str, Any]:
    """Assemble the tracked artifact: manifest provenance + the claims."""
    return {
        "schema": _SCHEMA,
        "tier": "tier-0",
        "source_manifest": manifest.get("source_url"),
        "csv_sha256": manifest.get("csv_sha256"),
        "card_count": len(manifest.get("cards", [])),
        "claim_count": len(result.claims),
        "uncitable_prior_source_skipped": {
            "count": result.uncitable_prior_source,
            "reason": UNCITABLE_PRIOR_SOURCE_REASON,
        },
        "claims": [claim.to_dict() for claim in result.claims],
    }


def main() -> int:
    """CLI: sweep ``data/manifests/latest.json`` -> the tracked artifact."""
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / "data" / "manifests" / "latest.json"
    out_path = repo_root / OUTPUT_PATH
    manifest = json.loads(manifest_path.read_text())
    result = sweep(manifest)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(build_output(manifest, result), indent=2) + "\n")
    print(
        f"tier-0 sweep: {len(result.claims)} claim(s) from "
        f"{len(manifest.get('cards', []))} cards"
    )
    print(f"  {result.uncitable_prior_source} card(s) skipped: the named prior source is not an address")
    print(f"  wrote {out_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
