"""Resolve third-party API keys for SDK client construction.

``settings`` reads ``.env`` through pydantic-settings but never exports it to
``os.environ``, so an SDK constructed with no ``api_key`` only sees the real
process environment. These helpers close that gap: the environment wins when
set, otherwise the settings (``.env``) value is used.
"""

from __future__ import annotations

import os

from pursue_index.config.settings import settings


def anthropic_api_key() -> str | None:
    """The Anthropic key: process environment first, then settings/.env.

    Returns ``None`` when neither has one, so the SDK raises its own error.
    """
    return (
        os.environ.get("ANTHROPIC_API_KEY")
        or settings.anthropic_api_key.get_secret_value()
        or None
    )
