"""Per-card ``pages_cleaned_qc.jsonl`` sidecar I/O + 4-tuple idempotency.

Each QC sidecar lives next to the existing ``pages_cleaned.jsonl`` on the
NAS: ``{settings.ocr_dir}/{card_id}/pages_cleaned_qc.jsonl``. One JSON
object per line, keyed by page number. Idempotent on
``(raw_sha256, cleaned_sha256, judge_model_id, judge_prompt_sha256)``
— any one of those four moving forces a re-grade.

Pure I/O — no Anthropic SDK, no settings dependency — so this file is
import-safe for tests and downstream readers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_existing(path: Path) -> dict[int, dict[str, Any]]:
    """Read an existing QC sidecar into ``{page_number: row_dict}``.

    Returns ``{}`` for missing files. Tolerates blank and malformed
    lines so a partial/interrupted write doesn't poison the
    idempotency check.
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
                continue
            page = row.get("page")
            if isinstance(page, int):
                rows[page] = row
    return rows


def write_row(path: Path, row: dict[str, Any]) -> None:
    """Append a single QC row to the sidecar, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def should_skip_qc(
    existing_row: dict[str, Any],
    *,
    raw_sha256: str,
    cleaned_sha256: str,
    judge_model_id: str,
    judge_prompt_sha256: str,
) -> bool:
    """Return True iff every load-bearing field on the existing row
    matches the new inputs.

    The 4-tuple idempotency mirrors the cleaner's 3-tuple plus the
    cleaned-sha guard: a page is re-graded if the cleaner re-cleaned
    it (different cleaned_sha) even on identical raw input.
    """
    expected = {
        "raw_sha256": raw_sha256,
        "cleaned_sha256": cleaned_sha256,
        "judge_model_id": judge_model_id,
        "judge_prompt_sha256": judge_prompt_sha256,
    }
    for key, want in expected.items():
        got = existing_row.get(key)
        if not isinstance(got, str) or got != want:
            return False
    return True
