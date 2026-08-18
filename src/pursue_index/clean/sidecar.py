"""Per-card ``pages_cleaned.jsonl`` sidecar I/O + row shaping.

Each sidecar lives next to the existing ``pages.jsonl`` on the NAS:
``{settings.ocr_dir}/{card_id}/pages_cleaned.jsonl``. One JSON object per
line, keyed by page number. Idempotent: re-running the cleanup pass for an
unchanged input is a skip via ``should_skip``.

Pure I/O + row shaping — no Anthropic SDK, no settings dependency — so
this file is import-safe for the build script and the tests. The
runner imports the I/O helpers from here so it stays
focused on orchestration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pursue_index.clean.prompt import (
    idempotency_key,
    input_sha256,
    output_sha256,
)


def read_pages(pages_path: Path) -> list[dict]:
    """Read ``pages.jsonl`` into a list of row dicts, ordered by page #."""
    rows: list[dict] = []
    with pages_path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
    rows.sort(key=lambda r: int(r.get("page", 0)))
    return rows


def row_from_clean(
    *,
    card_id: str,
    page: int,
    cleaned_text: str,
    raw_text: str,
    model_id: str,
    prompt_sha: str,
    cleanup_skipped: str | None = None,
) -> dict:
    """Build the per-row dict written to the sidecar JSONL.

    When ``cleanup_skipped`` is set (e.g. ``"length_divergence"``), the
    raw OCR text is stored in ``text_cleaned`` so downstream readers
    don't have to special-case missing data — the build step
    (``scripts/build_pages_cleaned.py``) is what filters these rows
    out of the deployed mirror.
    """
    row: dict = {
        "id": f"{card_id}-p{page}",
        "card_id": card_id,
        "page": page,
        "text_cleaned": cleaned_text,
        "model_id": model_id,
        "prompt_sha256": prompt_sha,
        "input_sha256": input_sha256(raw_text),
        "output_sha256": output_sha256(cleaned_text),
        "idempotency_key": idempotency_key(
            text=raw_text, model_id=model_id, prompt_sha=prompt_sha,
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if cleanup_skipped is not None:
        row["cleanup_skipped"] = cleanup_skipped
    return row


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


def should_skip(
    existing_row: dict[str, Any],
    new_input_sha: str,
    *,
    new_model_id: str | None = None,
    new_prompt_sha: str | None = None,
) -> bool:
    """Return True when an existing row already cleaned the same input.

    Skip semantics (per the runner's idempotency contract): a sidecar row
    is reusable only when ``(input, model, prompt)`` all match. A bump in
    any one of them invalidates the cache and forces a re-clean (PR #37):
    previously the helper only compared ``input_sha256``, so a
    prompt-only change would silently keep stale rows.

    A row missing ``input_sha256`` (or, when supplied, a missing
    ``model_id`` / ``prompt_sha256``) is treated as un-skippable: legacy
    or partial-write rows force a refresh rather than risk a false skip.

    The two-argument call form is preserved for back-compat — any caller
    that passes neither ``new_model_id`` nor ``new_prompt_sha`` keeps the
    old input-only behaviour.
    """
    existing_sha = existing_row.get("input_sha256")
    if not isinstance(existing_sha, str) or existing_sha != new_input_sha:
        return False
    if new_model_id is not None:
        existing_model = existing_row.get("model_id")
        if not isinstance(existing_model, str) or existing_model != new_model_id:
            return False
    if new_prompt_sha is not None:
        existing_prompt = existing_row.get("prompt_sha256")
        if not isinstance(existing_prompt, str) or existing_prompt != new_prompt_sha:
            return False
    return True
