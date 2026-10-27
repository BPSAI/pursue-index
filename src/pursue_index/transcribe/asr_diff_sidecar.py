"""Per-row ``asr_diff.jsonl`` sidecar I/O, next to the transcript it diffs.

One JSON object per line, keyed by ``row_key`` (``""`` for a card with a
single AUD row) -- the same card directory as ``pages.jsonl``/
``meta.json``/``utterances.jsonl`` (see ``pursue_index.transcribe.pages``).
Idempotent on the (engine_a, engine_b) pair AND the sha256 of engine A's
transcript text, and carries the card's ``meta.json`` ``finished_at`` as
``transcript_version``: a regenerated transcript is a different comparison,
so the old verdict never carries over to new text (the bundle drops a row
whose version is no longer current). A row written before these fields
existed matches neither and is compared again.

Pure I/O, mirrors ``clean.qc.sidecar``'s shape.
"""

from __future__ import annotations

import hashlib
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
    text_a_sha256: str | None = None,
    transcript_version: str | None = None,
) -> dict[str, Any]:
    """The sidecar row for one row's completed comparison."""
    return {
        "text_a_sha256": text_a_sha256,
        "transcript_version": transcript_version,
        "row_key": row_key,
        "engine_a": engine_a,
        "engine_b": engine_b,
        "threshold": threshold,
        "status": status,
        **result.to_dict(),
    }


def text_sha256(text: str) -> str:
    """Fingerprint of engine A's transcript text for the idempotency check."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def should_skip(
    existing_row: dict[str, Any], *, engine_a: str, engine_b: str,
    text_a_sha256: str | None = None, transcript_version: str | None = None,
) -> bool:
    """True iff the existing row already compares this exact comparison.

    ``text_a_sha256`` / ``transcript_version`` identify the current
    transcript; each, when given, must match the row's. ``None`` (a cost
    preview holds no transcript text) skips that check.
    """
    if existing_row.get("engine_a") != engine_a or existing_row.get("engine_b") != engine_b:
        return False
    if text_a_sha256 is not None and existing_row.get("text_a_sha256") != text_a_sha256:
        return False
    return transcript_version is None or existing_row.get("transcript_version") == transcript_version


def expected_row_keys(meta: object) -> set[str] | None:
    """Row keys a card's ``meta.json`` says carry a transcript, or ``None``
    when the meta is unusable (not ``status: ok``), so coverage is unknowable."""
    if not isinstance(meta, dict) or meta.get("status") != "ok":
        return None
    rows = meta.get("rows") or [{"row_key": ""}]
    return {str(r.get("row_key", "") or "") for r in rows if isinstance(r, dict)}


def transcript_version(card_dir: Path) -> str | None:
    """The card's current transcript version (``meta.json`` ``finished_at``),
    or ``None`` when it cannot be read."""
    version = (read_meta(card_dir) or {}).get("finished_at")
    return version if isinstance(version, str) and version else None


def read_meta(card_dir: Path) -> dict[str, Any] | None:
    """The card's ``meta.json`` as a dict, or ``None`` when absent/unreadable."""
    try:
        data = json.loads((card_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
