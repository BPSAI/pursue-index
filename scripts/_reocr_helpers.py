"""Pure helpers + IO wrappers extracted from ``reocr_altered.py``.

Kept in a sibling module (and prefixed ``_``) so:

* The main script stays under the architecture-rules file-size +
  function-count ceilings.
* These can be unit-tested without spinning up the
  ``ThreadPoolExecutor`` / Anthropic SDK / pdf2image deps the main
  script needs.

No business logic in this module: the per-card orchestration lives
in ``reocr_altered.py::ocr_card``; we only know how to *prepare*
inputs for it.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# archive_key shape: ``archive/<lowercase-64-hex-sha>.pdf``. Mirrors the
# worker's ``BYTE_SHA_RE`` (``worker/pdf.js::BYTE_SHA_RE``). Anchored so
# path-traversal attempts (``archive/../``) and trailing-dot tricks
# (``archive/<sha>.pdf.png``) reject. .pdf only because ``fetch_r2_pdf``
# is the PDF-specific path; .mp4 / .png archive_keys go through other
# code paths and never reach this function.
_ARCHIVE_KEY_PDF_RE = re.compile(r"^archive/[a-f0-9]{64}\.pdf$")

# Sonnet 4.6 pricing per Anthropic (Sprint 4h kick-off, 2026-05-20):
# $3/MTok input, $15/MTok output.
SONNET_46_INPUT_USD_PER_MTOK = 3.0
SONNET_46_OUTPUT_USD_PER_MTOK = 15.0


class CostCapExceededError(RuntimeError):
    """Estimated cost exceeded the ``--max-spend-usd`` cap mid-run.

    Cards whose pages.jsonl entries were written before the cap fired
    persist — re-running the script picks up from there. Per-page
    granularity ensures no completed-page-cost is lost.
    """


@dataclass
class UsageTracker:
    """Running totals across all OCR calls in a single run.

    Thread-safe under the GIL for the ``.add()`` increment path. A
    slightly stale read during a concurrent ``.add()`` is fine for
    cost-cap gating — worst case a few extra in-flight calls fire
    before the cap-exceed propagates.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, *, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.calls += 1

    def estimated_cost_usd(self) -> float:
        return estimate_cost_usd(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


def estimate_cost_usd(*, input_tokens: int, output_tokens: int) -> float:
    """Sonnet 4.6 pricing. ``MTok`` = 10**6 tokens."""
    input_cost = (input_tokens / 1_000_000) * SONNET_46_INPUT_USD_PER_MTOK
    output_cost = (output_tokens / 1_000_000) * SONNET_46_OUTPUT_USD_PER_MTOK
    return input_cost + output_cost


def select_ocr_targets(byte_history: dict) -> list[dict]:
    """Return OCR-eligible cards. Skips non-PDF (e.g. .mp4 video)
    current_entry. Sorted by card_id for deterministic resume."""
    targets: list[dict] = []
    for card_id, entries in byte_history.items():
        if not entries:
            continue
        current = entries[0]  # newest-first per build_byte_history
        archive_key = current.get("archive_key", "")
        if not archive_key.lower().endswith(".pdf"):
            continue
        targets.append({
            "card_id": card_id,
            "byte_sha256": current["byte_sha256"],
            "archive_key": archive_key,
            "asset_filename": current.get("asset_filename"),
        })
    targets.sort(key=lambda t: t["card_id"])
    return targets


def resume_from_page(jsonl_path: Path) -> int:
    """Return the next page number to OCR (1-indexed).

    Reads existing pages.jsonl entries and returns ``max(page) + 1``.
    Returns 1 if the file is missing OR any line is malformed
    (corrupt file = restart; safer than misaligning page indices).

    Callers that intend to append to the file should call
    ``truncate_jsonl_to_valid_prefix`` first — otherwise a torn line
    permanently traps every rerun at page 1, re-spending API budget
    indefinitely (Codex PR #72 P1).
    """
    if not jsonl_path.is_file():
        return 1
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except OSError:
        return 1
    highest = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return 1
        page = row.get("page")
        if isinstance(page, int) and page > highest:
            highest = page
    return highest + 1


def truncate_jsonl_to_valid_prefix(jsonl_path: Path) -> int:
    """Rewrite ``jsonl_path`` to contain only the longest contiguous
    prefix of valid JSON lines, returning the next-page-to-OCR (i.e.,
    ``max(valid page) + 1``).

    Codex PR #72 P1 fix: a torn write leaves a malformed line.
    ``resume_from_page`` returns 1 (safe but lossy) and any subsequent
    appends would land BEHIND the malformed line — meaning the
    corrupt prefix persists forever and every later rerun re-OCRs
    every page, re-spending the full per-card API budget. This
    helper repairs the file in place so the resume loop can pick up
    cleanly without re-spending.

    Idempotent: if every line parses, the file is rewritten to its
    own contents (cheap; no semantic change).

    Returns 1 when the file is missing or the first line is already
    torn (no valid prefix to keep).
    """
    if not jsonl_path.is_file():
        return 1
    valid_lines: list[str] = []
    highest = 0
    try:
        text = jsonl_path.read_text(encoding="utf-8")
    except OSError:
        return 1
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            break
        valid_lines.append(line)
        page = row.get("page")
        if isinstance(page, int) and page > highest:
            highest = page
    # Rewrite the file with only the validated lines (atomic via
    # temp+rename so an interrupt here doesn't compound the problem).
    rewritten = ("\n".join(valid_lines) + "\n") if valid_lines else ""
    tmp = jsonl_path.with_suffix(jsonl_path.suffix + ".tmp")
    tmp.write_text(rewritten, encoding="utf-8")
    tmp.replace(jsonl_path)
    return highest + 1


def fetch_r2_pdf(client: Any, archive_key: str, bucket: str = "pursue-pdfs") -> bytes:
    """Stream PDF bytes from R2 into memory.

    Validates ``archive_key`` shape before the boto3 call so a corrupted
    byte-history entry surfaces as a typed ``ValueError`` here instead
    of a confusing ``NoSuchKey`` from R2 (Sprint 4i #8, laverna P3).
    """
    if not _ARCHIVE_KEY_PDF_RE.match(archive_key):
        raise ValueError(
            f"archive_key {archive_key!r} doesn't match the expected shape "
            "`archive/<64-hex-sha>.pdf` — refusing to forward to R2."
        )
    obj = client.get_object(Bucket=bucket, Key=archive_key)
    return obj["Body"].read()


def append_jsonl(path: Path, row: dict) -> None:
    """Append one row. nayru M1: dropped fsync — the resume_from_page
    handler restarts cleanly on torn-write JSON parse failure, so
    flush() is sufficient and avoids 3,425 fsyncs per OCR run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
