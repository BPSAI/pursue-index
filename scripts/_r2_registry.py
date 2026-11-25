"""The asset-bytes registry file: read in file order, grouped per card, and appended to."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_registry(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Return ``{card_id: [row, row, ...]}`` sorted newest-last by fetched_at.

    Robust against malformed rows: a line missing ``card_id`` or
    failing JSON parse is skipped, not raised. The registry is
    append-only + content-addressed and is committed by multiple
    workflows; a single corrupt mid-write line shouldn't take down
    every subsequent run.
    """
    return group_registry(load_registry_rows(path))


def load_registry_rows(path: Path) -> list[dict[str, Any]]:
    """The registry's usable rows in file order (a position here is what a gate marker counts)."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("card_id"):
                rows.append(row)
    return rows


def group_registry(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """``{card_id: [row, ...]}`` newest-last; the row objects are shared with ``rows``."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row["card_id"], []).append(row)
    for card_rows in out.values():
        card_rows.sort(key=lambda r: r.get("fetched_at", ""))
    return out


def append_registry(path: Path, entry: dict[str, Any]) -> None:
    """Append one JSONL row to the asset-bytes registry.

    Contract pin: every row MUST be on a single line. The workflow's
    "count new rows" step uses `grep -c '^+{'` on the diff to report
    how many rows landed in a given commit; that grep relies on each
    row starting with `{` and ending with `}\n` — i.e., no pretty-
    printed multi-line JSON. ``json.dumps`` with default settings
    enforces this (no indent argument supplied), but the contract is
    load-bearing for the workflow's row-count source, so this comment
    serves as the regression alert: do NOT add `indent=` here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        # json.dumps default: compact, no indent → single-line per row.
        fh.write(json.dumps(entry) + "\n")
