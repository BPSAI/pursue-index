"""Suite-wide isolation from the invoking shell's configuration.

The suite must give the same result whether or not the shell that runs it has
``PURSUE_*`` variables exported or a ``.env`` next to the working directory.
Every test therefore starts with:

* no ``PURSUE_*`` variable in ``os.environ`` (subprocesses inherit this);
* ``Settings`` not reading any ``.env`` file;
* the lazy ``settings`` singleton unbuilt, so it is rebuilt from the
  stripped environment on first use instead of reusing values cached by an
  earlier test or at import time.

A test that needs a ``PURSUE_*`` value sets it with ``monkeypatch.setenv``;
this fixture runs first, so that value is the one the test sees.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pursue_index.config.settings import Settings, settings


@pytest.fixture(autouse=True)
def _hermetic_pursue_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.upper().startswith("PURSUE_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    settings.__dict__.pop("_settings", None)
    yield
    settings.__dict__.pop("_settings", None)


@pytest.fixture
def pursue_data_root(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An existing, empty data root exported as ``PURSUE_DATA_ROOT``, for
    tests that drive a real (non-dry) promotion, which refuses without one."""
    root = tmp_path_factory.mktemp("data-root")
    monkeypatch.setenv("PURSUE_DATA_ROOT", str(root))
    return root
