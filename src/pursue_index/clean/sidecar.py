"""Per-card ``pages_cleaned.jsonl`` sidecar I/O.

Each sidecar lives next to the existing ``pages.jsonl`` on the NAS:
``{settings.ocr_dir}/{card_id}/pages_cleaned.jsonl``. One JSON object per
line, keyed by page number. Idempotent: re-running the cleanup pass for an
unchanged input is a skip via ``should_skip``.

Pure I/O — no Anthropic SDK, no settings dependency — so this file is
import-safe for the build script and the tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_existing(path: Path) -> dict[int, dict[str, Any]]:
    """Read an existing sidecar JSONL into ``{page_number: row_dict}``.

    Returns ``{}`` when the file doesn't exist (first run). Tolerates blank
    lines and trailing whitespace so a partial/interrupted write doesn't
    poison the idempotency check.
    """
    if not path.exists():
        return {}
    rows: dict[int, dict[str, Any]] = {}
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                # A genuinely corrupt line — better to skip than crash the
                # whole pilot. The runner will overwrite this page next pass.
                continue
            page = row.get("page")
            if isinstance(page, int):
                rows[page] = row
    return rows


def write_row(path: Path, row: dict[str, Any]) -> None:
    """Append a single row to the sidecar JSONL, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def should_skip(existing_row: dict[str, Any], new_input_sha: str) -> bool:
    """Return True when an existing row already cleaned the same input.

    A row without ``input_sha256`` is treated as un-skippable (forces a
    re-clean) — that handles the legacy/partial-write case.
    """
    existing_sha = existing_row.get("input_sha256")
    if not isinstance(existing_sha, str):
        return False
    return existing_sha == new_input_sha
