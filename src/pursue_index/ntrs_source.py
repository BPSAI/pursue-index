"""NASA NTRS metadata source for unresolved NASA cards (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.resolved_claim import ResolvedClaim

OUTPUT_PATH = Path("data") / "provenance" / "ntrs-claims.json"
SCHEMA = "ntrs-claims/v1"
MATCH_THRESHOLD = 0.9
MIN_SHARED_TOKENS = 2
SOURCE_LABEL = "NASA NTRS"

RESULT_CLAIM = "claim"
RESULT_POST_DATING = "post_dating_copy_found"
RESULT_NO_COPY = "no_copy_found"
RESULT_UNDATED = "match_undated"
RESULT_NO_RELEASE_DATE = "release_date_unreadable"


def normalize_query(title: str) -> str:
    return ""


def token_set_ratio(a: str, b: str) -> float:
    return 0.0


def title_matches(card_title: str, result_title: str) -> bool:
    return False


@dataclass(frozen=True)
class CardSearch:
    card_id: str
    query: str
    searched_date: date
    result: str
    claim: ResolvedClaim | None = None
    copies: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {}


def evaluate_card(card: dict[str, Any], response: dict[str, Any], searched_date: date) -> CardSearch:
    return CardSearch(str(card.get("card_id")), "", searched_date, "")


def unresolved_nasa_cards(manifest: dict[str, Any], catalogue: Any = ()) -> list[dict[str, Any]]:
    return []


def run_searches(manifest: dict[str, Any], fetcher: Any, searched_date: date, catalogue: Any = ()) -> list[CardSearch]:
    return []


def build_output(manifest: dict[str, Any], searches: list[CardSearch], fetch_counts: dict[str, Any]) -> dict[str, Any]:
    return {}


def main() -> int:
    return 1
