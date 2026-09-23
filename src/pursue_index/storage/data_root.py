"""Data-root reachability and OCR coverage for ``pursue storage verify``.

``configured`` (``PURSUE_DATA_ROOT`` resolves) and ``mounted`` (the path answers
a ``stat``) are different facts: an unmounted NAS leaves the env var set, and
the derivative builders then read an empty tree and silently rebuild a
smaller corpus. Credential-free, like the rest of the storage contract.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_ROOT_ENV = "PURSUE_DATA_ROOT"


@dataclass(frozen=True)
class DataRootProbe:
    configured: bool
    mounted: bool
    root: Path | None = None


def probe_data_root(env: Mapping[str, str]) -> DataRootProbe:
    """``stat`` the configured data root; it must be a directory to count."""
    raw = env.get(DATA_ROOT_ENV)
    if not raw:
        return DataRootProbe(configured=False, mounted=False)
    root = Path(raw)
    try:
        mounted = stat.S_ISDIR(os.stat(root).st_mode)
    except OSError:
        mounted = False
    return DataRootProbe(configured=True, mounted=mounted, root=root)


def ocr_coverage(
    ocr_dir: Path, manifest_cards: Iterable[Mapping[str, Any]]
) -> tuple[int, int]:
    """``(manifest cards with an ocr/<id>/pages.jsonl, manifest cards)``."""
    ids = [str(c["card_id"]) for c in manifest_cards]
    covered = sum(1 for cid in ids if (ocr_dir / cid / "pages.jsonl").exists())
    return covered, len(ids)


def render_data_root_lines(
    probe: DataRootProbe, coverage: tuple[int, int] | None
) -> list[str]:
    """The ``configured`` / ``mounted`` / ``ocr coverage`` report lines."""
    lines = [
        f"data root configured: {'yes' if probe.configured else 'no'}",
        f"data root mounted: {'yes' if probe.mounted else 'no'}",
    ]
    if coverage is None:
        lines.append("ocr coverage: n/a (data root not mounted or manifest missing)")
    else:
        lines.append(f"ocr coverage: {coverage[0]}/{coverage[1]} cards")
    return lines
