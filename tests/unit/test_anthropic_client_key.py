"""The Anthropic clients take the key from settings (.env) when the process
environment lacks it, and the environment wins when both are set.

Dummy keys only; the SDK constructor is faked, nothing touches the network.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from pursue_index.clean import client as clean_client
from pursue_index.clean.qc import judge as qc_judge
from pursue_index.config import settings
from pursue_index.config.credentials import anthropic_api_key
from pursue_index.ocr import llm as ocr_llm
from pursue_index.vision import client as vision_client

_ENV_KEY = "dummy-env-key"
_SETTINGS_KEY = "dummy-settings-key"

_FACTORIES = [
    (ocr_llm, "_get_anthropic_client"),
    (vision_client, "_get_anthropic_client"),
    (clean_client, "_get_client"),
    (qc_judge, "_get_client"),
]


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import anthropic

    seen: dict[str, Any] = {}

    class _Fake:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(anthropic, "Anthropic", _Fake)
    for mod, _ in _FACTORIES:
        monkeypatch.setattr(mod, "_client", None)
    return seen


def test_helper_prefers_settings_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_SETTINGS_KEY))
    assert anthropic_api_key() == _SETTINGS_KEY


def test_helper_env_wins_over_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", _ENV_KEY)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_SETTINGS_KEY))
    assert anthropic_api_key() == _ENV_KEY


def test_helper_none_when_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    assert anthropic_api_key() is None


@pytest.mark.parametrize(("mod", "name"), _FACTORIES)
def test_client_receives_settings_key(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], mod: Any, name: str
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_SETTINGS_KEY))
    getattr(mod, name)()
    assert captured["api_key"] == _SETTINGS_KEY


@pytest.mark.parametrize(("mod", "name"), _FACTORIES)
def test_client_env_wins_when_both_set(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], mod: Any, name: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", _ENV_KEY)
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_SETTINGS_KEY))
    getattr(mod, name)()
    assert captured["api_key"] == _ENV_KEY


def test_settings_repr_does_not_leak_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(_SETTINGS_KEY))
    assert _SETTINGS_KEY not in repr(settings._real())
