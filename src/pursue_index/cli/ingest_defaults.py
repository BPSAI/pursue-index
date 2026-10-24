"""Data-path defaults for ``pursue ingest``, resolved when a command runs.

Resolving at import time would run the repo-root trust check while the
package loads; as callables, an untrusted working directory is reported by
the command that needs the data root.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pursue_index.paths import repo_root

_DATA_FILES = {
    "DEFAULT_APPROVAL_LOG": ("tranche-approval-log.jsonl",),
    "DEFAULT_ALIASES": ("card-aliases.json",),
    # Must match scripts/tranche_diff.py::DEFAULT_OUT_DIR, and must be tracked —
    # `.paircoder/` is gitignored, so receipts written there never get committed.
    "DEFAULT_DIFF_DIR": ("tranche-diffs",),
    "DEFAULT_MANIFEST_SNAPSHOTS": ("manifests", "snapshots"),
    "DEFAULT_LATEST_MANIFEST": ("manifests", "latest.json"),
    "DEFAULT_WORKLIST": ("ingest-worklist.txt",),
    "DEFAULT_ASSET_REGISTRY": ("asset-bytes-registry.jsonl",),
}


def _default(name: str) -> Callable[[], Path]:
    """Resolve a data path when the command runs, never at import time."""
    return lambda: repo_root().joinpath("data", *_DATA_FILES[name])


def __getattr__(name: str) -> Path:
    if name in _DATA_FILES:
        return _default(name)()
    raise AttributeError(name)
