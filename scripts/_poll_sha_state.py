"""Last-known sha file helpers for ``poll_pursue.py``.

Kept in a sibling module (``_``-prefixed, like ``_poll_gh_io.py``) so the
entry script stays under the 200-line warning threshold. The file format,
``{sha256}  {iso8601}\n``, is also read by ``build_card_alt_titles.py``.
"""

from __future__ import annotations

import json
from pathlib import Path


def _read_last_known(state_path: Path) -> str:
    """Sha from the state file, or ``""`` if missing/empty.

    File format: ``{sha256}  {iso8601}\n`` (two spaces between fields).
    """
    if not state_path.exists():
        return ""
    text = state_path.read_text().strip()
    return text.split()[0] if text else ""


def _read_manifest_sha(manifest_path: Path) -> str:
    """``csv_sha256`` from ``manifest_path``, or ``""`` on miss/parse-error.

    Fallback used when the state file is missing — keeps the state
    file and the manifest in agreement so a manual ``pursue scrape
    run`` doesn't look like an upstream change on the next tick.
    """
    if not manifest_path.exists():
        return ""
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    sha = data.get("csv_sha256", "") if isinstance(data, dict) else ""
    return sha if isinstance(sha, str) else ""


def resolve_old_sha(state_path: Path, manifest_path: Path | None) -> str:
    """State file wins; manifest is fallback; both missing => bootstrap."""
    sha = _read_last_known(state_path)
    if sha:
        return sha
    return _read_manifest_sha(manifest_path) if manifest_path is not None else ""


def write_state(state_path: Path, sha: str, ts: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(f"{sha}  {ts}\n")
