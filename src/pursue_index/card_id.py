"""The shape of a card_id, enforced where ids become filesystem paths."""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = ["CARD_ID_PATTERN", "InvalidCardIdError", "require_card_id", "require_card_ids"]

CARD_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


class InvalidCardIdError(ValueError):
    """A card_id that is not 16 lowercase hex characters."""


def require_card_id(card_id: object) -> str:
    """Return ``card_id`` unchanged, or raise :class:`InvalidCardIdError`."""
    if not isinstance(card_id, str) or not CARD_ID_PATTERN.fullmatch(card_id):
        raise InvalidCardIdError(
            f"invalid card_id {str(card_id)[:40]!r}: expected 16 lowercase hex characters"
        )
    return card_id


def require_card_ids(card_ids: Iterable[object]) -> list[str]:
    return [require_card_id(c) for c in card_ids]
