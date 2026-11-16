"""The environment each autopilot child step gets: an allowlist, never the
whole parent environment.

Every child gets the base allowlist below plus ``NO_PURSUE_DOTENV=1``, so a
child that loads settings does not read the checkout's ``.env`` either. Only
``pursue storage verify`` also gets the storage credentials, which it checks
for by name, and only the freshness recheck's ``git fetch`` gets the SSH agent. The scheduler must export every variable a step needs; see
``EXPORTED_BY_SCHEDULER``. This module handles names only and never logs or
transforms a value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Process basics and locale. No GIT_*, PYTHON*, LD_*, SSH agent or tokens:
# those change what a child runs or who it acts as.
_BASE_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TERM", "TZ",
    "LANG", "LC_ALL", "LC_CTYPE",
)
# Pipeline settings (PURSUE_DATA_ROOT and the other PURSUE_* knobs), minus any
# name that looks like a credential.
_BASE_PREFIX = "PURSUE_"
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)

# The SSH agent, for the freshness recheck's `git fetch` only.
SSH_KEYS = ("SSH_AUTH_SOCK", "SSH_AGENT_PID")

# Checked by `pursue storage verify` (pursue_index.storage.contract); only that
# step receives them.
STORAGE_KEYS = (
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID",
    "BACKUP_R2_ACCOUNT_ID", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY",
)

# What the scheduled autopilot's environment must export (names only).
EXPORTED_BY_SCHEDULER = ("PATH", "HOME", "PURSUE_DATA_ROOT", *STORAGE_KEYS)


def base_env(environ: Mapping[str, str], pythonpath: str) -> dict[str, str]:
    """The allowlisted environment every child step gets."""
    env = {k: environ[k] for k in _BASE_KEYS if k in environ}
    env.update({k: v for k, v in environ.items()
                if k.startswith(_BASE_PREFIX) and not _SECRET_NAME.search(k)})
    env["NO_PURSUE_DOTENV"] = "1"
    env["PYTHONPATH"] = pythonpath
    return env


def storage_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The storage credentials, for `pursue storage verify` only."""
    return {k: environ[k] for k in STORAGE_KEYS if k in environ}


def ssh_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The SSH agent variables, for the freshness recheck's fetch only."""
    return {k: environ[k] for k in SSH_KEYS if k in environ}
