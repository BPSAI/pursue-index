"""Per-row ``asr_diff.jsonl`` sidecar I/O, next to the transcript it diffs.

One JSON object per line, keyed by ``row_key`` (``""`` for a card with a
single AUD row) -- the same card directory as ``pages.jsonl``/
``meta.json``/``utterances.jsonl`` (see ``pursue_index.transcribe.pages``).
Idempotent on the (engine_a, engine_b) pair: engine A's transcript is
already final once written, so the pair alone is enough to say "this
exact comparison already ran."

Pure I/O, mirrors ``clean.qc.sidecar``'s shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pursue_index.transcribe.asr_diff import AsrDiffResult

SIDECAR_FILE = "asr_diff.jsonl"


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    """Read an existing sidecar into ``{row_key: row_dict}``.

    Returns ``{}`` for a missing file and tolerates blank/malformed lines
    so a partial write doesn't poison the idempotency check.
    """
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            row_key = row.get("row_key")
            if isinstance(row_key, str):
                rows[row_key] = row
    return rows


def write_row(path: Path, row: dict[str, Any]) -> None:
    """Append a single diff row to the sidecar, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_row(
    *,
    row_key: str,
    engine_a: str,
    engine_b: str,
    result: AsrDiffResult,
    threshold: float,
    status: str,
) -> dict[str, Any]:
    """The sidecar row for one row's completed comparison."""
    return {
        "row_key": row_key,
        "engine_a": engine_a,
        "engine_b": engine_b,
        "threshold": threshold,
        "status": status,
        **result.to_dict(),
    }


def should_skip(existing_row: dict[str, Any], *, engine_a: str, engine_b: str) -> bool:
    """True iff the existing row already compares this exact engine pair."""
    return (
        existing_row.get("engine_a") == engine_a
        and existing_row.get("engine_b") == engine_b
    )
