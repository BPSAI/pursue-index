"""Suite-wide isolation from the invoking shell's configuration.

The suite must give the same result whether or not the shell that runs it has
``PURSUE_*`` variables exported or a ``.env`` next to the working directory.

At import time, before anything imports ``pursue_index`` (whose
``__init__`` builds the settings singleton and configures logging from it),
this module:

* removes every ``PURSUE_*`` variable from ``os.environ`` for the session;
* sets ``NO_PURSUE_DOTENV=1``, the test-only switch ``Settings`` reads when
  its class is defined, so neither this interpreter nor any subprocess it
  spawns (scripts, the ``pursue`` CLI) reads a ``.env`` file. The name is
  deliberately outside the ``PURSUE_`` prefix so the strip never removes it.

Every test then additionally starts with no ``PURSUE_*`` variable (a test's
own ``monkeypatch.setenv`` runs after this and wins) and an unbuilt lazy
``settings`` singleton, so nothing cached by an earlier test leaks in.
"""

from __future__ import annotations

import os
import sys

_PRELOADED = "pursue_index" in sys.modules

for _name in list(os.environ):
    if _name.upper().startswith("PURSUE_"):
        del os.environ[_name]
os.environ["NO_PURSUE_DOTENV"] = "1"

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

import pursue_index  # noqa: E402
from pursue_index.config.settings import Settings, settings  # noqa: E402


def reset_pursue_settings() -> None:
    """Drop the lazy ``settings`` singleton's cached ``Settings`` so the next
    attribute access rebuilds it from the current environment."""
    settings.__dict__.pop("_settings", None)


if _PRELOADED:
    # Something imported the package before this conftest stripped the
    # environment; rebuild settings and logging from the clean state.
    Settings.model_config["env_file"] = None
    reset_pursue_settings()
    pursue_index._configure_logging()


@pytest.fixture(autouse=True)
def _hermetic_pursue_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.upper().startswith("PURSUE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("NO_PURSUE_DOTENV", "1")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    reset_pursue_settings()
    yield
    reset_pursue_settings()


@pytest.fixture
def pursue_data_root(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An existing, empty data root exported as ``PURSUE_DATA_ROOT``, for
    tests that drive a real (non-dry) promotion, which refuses without one."""
    root = tmp_path_factory.mktemp("data-root")
    monkeypatch.setenv("PURSUE_DATA_ROOT", str(root))
    return root
