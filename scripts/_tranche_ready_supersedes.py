"""The tranche-ready record's ``supersedes`` list (R7C.31).

The stale-edge guard (R7C.30, ``_poll_guard.py``) records every sha it has
observed in ``data/poll-state.json``'s ``seen`` list, oldest first, and opens
nothing for a stale one. A sha observed after the prior promoted manifest and
before the one this record is for never shipped, so this record subsumes it.
Each such sha whose CSV bytes are archived (``data/raw/csv/<sha>.csv``) is
listed with the reason the evidence supports:

* ``subset-of-current`` -- its rows are a non-empty strict subset of the new
  manifest's (``_poll_stale_checks.is_row_subset_of_manifest``, the same
  check the guard applies on a first sighting);
* ``replaced-by-newer`` -- it has its own tranche-ready record, so it was a
  confirmed change that a newer sha replaced before hand-off.

A sha with neither signal (an older ``Last-Modified`` is not persisted per
sha) is left out rather than given a reason the evidence does not support.
Nothing here changes how staleness is detected; it only reads what the guard
and the archive already hold.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _poll_stale_checks import is_row_subset_of_manifest

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _seen_between(poll_state: Path, prior_sha: str | None, new_sha: str) -> list[str]:
    try:
        seen = json.loads(poll_state.read_text(encoding="utf-8")).get("seen") or []
    except (OSError, ValueError, AttributeError):
        return []
    if prior_sha not in seen or new_sha not in seen:
        return []
    start, end = seen.index(prior_sha), seen.index(new_sha)
    return [s for s in seen[start + 1:end] if isinstance(s, str) and _SHA256.fullmatch(s)]


def derive_supersedes(
    poll_state: Path, csv_archive: Path, prior_sha: str | None, new_sha: str,
    new_manifest_path: Path, ready_dir: Path,
) -> list[dict[str, Any]]:
    """Unshipped shas between the prior manifest and ``new_sha``, with reasons."""
    out = []
    for sha in _seen_between(poll_state, prior_sha, new_sha):
        csv_path = csv_archive / f"{sha}.csv"
        if not csv_path.is_file():
            continue
        if is_row_subset_of_manifest(new_manifest_path, csv_path.read_bytes()):
            reason = "subset-of-current"
        elif (ready_dir / f"{sha[:12]}.json").is_file():
            reason = "replaced-by-newer"
        else:
            continue
        out.append({"tranche_sha256": sha, "tranche_sha12": sha[:12], "issue": None,
                    "reason": reason})
    return out
