"""The environment each autopilot child step gets: an allowlist, never the
whole parent environment.

Every child gets the base allowlist below plus ``NO_PURSUE_DOTENV=1``, so a
child that loads settings does not read the checkout's ``.env`` either. Only
``pursue storage verify`` also gets the storage credentials, which it checks
for by name. The scheduler must export every variable a step needs; see
``EXPORTED_BY_SCHEDULER``. This module handles names only and never logs or
transforms a value.
"""

from __future__ import annotations

from collections.abc import Mapping

# Process basics and locale. No GIT_*, PYTHON*, LD_*, SSH agent or tokens:
# those change what a child runs or who it acts as.
_BASE_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TERM", "TZ",
    "LANG", "LC_ALL", "LC_CTYPE",
)
# The pipeline settings a child may need: an explicit allowlist, not a prefix.
# tests/unit/test_tranche_autopilot_child_env.py fails if a PURSUE_* name
# appears in the code without being listed here or in PURSUE_EXCLUDED.
PURSUE_ALLOWED = (
    "PURSUE_ALLOW_NO_EXCLUSIONS", "PURSUE_API_HOST", "PURSUE_API_PORT",
    "PURSUE_AUGMENT_SKIP_HASH_CHECK", "PURSUE_CF_ACCOUNT_ID", "PURSUE_CSV_URL",
    "PURSUE_DATA_ROOT", "PURSUE_DOTS_MODEL", "PURSUE_DOTS_PYTHON", "PURSUE_DOTS_WORKER",
    "PURSUE_DOWNLOAD_CONCURRENCY", "PURSUE_DOWNLOAD_RETRIES", "PURSUE_DOWNLOAD_VIDEOS",
    "PURSUE_EMBED_MODEL", "PURSUE_EMBED_PROVIDER",
    "PURSUE_INGEST_AUTO_APPROVE_METADATA_RESAVES", "PURSUE_LOG_FORMAT", "PURSUE_LOG_LEVEL",
    "PURSUE_MANIFESTS_DIR", "PURSUE_OCR_DPI", "PURSUE_OCR_ENGINE",
    "PURSUE_OCR_LLM_CONCURRENCY", "PURSUE_OCR_LLM_MODEL", "PURSUE_OCR_LLM_PROVIDER",
    "PURSUE_OCR_LLM_THRESHOLD", "PURSUE_REPO_ROOT", "PURSUE_SCRAPE_USER_AGENT",
    "PURSUE_STRICT_INVARIANTS", "PURSUE_TESSERACT_BIN",
)
# Never passed: a credential, a URL that can carry one, or a dotenv path.
PURSUE_EXCLUDED = ("PURSUE_CF_API_TOKEN", "PURSUE_DB_URL", "PURSUE_DOTENV")

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
    env.update({k: environ[k] for k in PURSUE_ALLOWED if k in environ})
    env["NO_PURSUE_DOTENV"] = "1"
    env["PYTHONPATH"] = pythonpath
    return env


def storage_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The storage credentials, for `pursue storage verify` only."""
    return {k: environ[k] for k in STORAGE_KEYS if k in environ}

