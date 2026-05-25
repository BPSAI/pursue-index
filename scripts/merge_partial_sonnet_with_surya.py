"""Merge partial-Sonnet `pages.jsonl.sonnet-partial` backups with the
full-Surya `pages.jsonl` produced by a follow-up surya re-OCR. Per-page,
prefer the Sonnet row; fall back to Surya where Sonnet didn't reach.

Sprint 4q deferred re-OCR (2026-05-22 → 2026-05-23): two FBI HQ
62-83894 series cards hit Anthropic's content-filter policy mid-OCR
after Sonnet had successfully transcribed the first 74 (resp. 87)
pages. We backed up the partial Sonnet output, re-ran the cards with
`--engine surya --force`, and now merge: Sonnet wins where present,
Surya fills the rest. The result is the best quality possible given
the content-filter blast zone.

Usage::

    python scripts/merge_partial_sonnet_with_surya.py \\
        --card-id f85532f0514320be \\
        --card-id 7d58f0cac741650a

Idempotent: rerunning on already-merged files is a no-op as long as the
`.sonnet-partial` backup is still present. Bumps meta.json `status` to
`ok` and `engine` to `llm+surya-mixed` so the downstream rebuild
includes the card with mixed-engine per-page provenance.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

NAS_OCR_ROOT = Path("/mnt/nas/personal/pursue/ocr")


def _load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, return list of parsed objects."""
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def merge_rows(sonnet_rows: list[dict], surya_rows: list[dict]) -> list[dict]:
    """Per-page merge: Sonnet wins, Surya fills gaps.

    Both lists carry per-page objects with a ``page`` key. Sonnet rows
    have ``engine="llm"`` (or similar); Surya rows have ``engine="surya"``.
    Returns a new list ordered by page number with the Sonnet row picked
    whenever a page appears in both.
    """
    sonnet_by_page = {r["page"]: r for r in sonnet_rows}
    merged: list[dict] = []
    for row in surya_rows:
        if row["page"] in sonnet_by_page:
            merged.append(sonnet_by_page[row["page"]])
        else:
            merged.append(row)
    return merged


def _write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    """Write rows as JSONL via a tmp file + rename for atomicity."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    tmp.replace(path)


def _update_meta(meta_path: Path, page_count: int, sonnet_count: int) -> None:
    """Mark the card ``status=ok`` with mixed-engine annotation."""
    meta = json.loads(meta_path.read_text())
    meta["status"] = "ok"
    meta["engine"] = "llm+surya-mixed"
    meta["page_count"] = page_count
    meta["mixed_engine_breakdown"] = {
        "llm_pages": sonnet_count,
        "surya_pages": page_count - sonnet_count,
    }
    meta["content_filter_recovery_at"] = datetime.now(UTC).isoformat()
    # Preserve the original error string under a renamed key for audit.
    if "error" in meta:
        meta["content_filter_error"] = meta.pop("error")
    meta_path.write_text(json.dumps(meta, indent=2))


def merge_card(card_id: str, dry_run: bool = False) -> dict:
    """Merge one card's partial-Sonnet + Surya output. Returns a summary dict."""
    card_dir = NAS_OCR_ROOT / card_id
    surya_path = card_dir / "pages.jsonl"
    sonnet_path = card_dir / "pages.jsonl.sonnet-partial"
    meta_path = card_dir / "meta.json"

    if not sonnet_path.exists():
        raise FileNotFoundError(
            f"Missing Sonnet partial backup: {sonnet_path}. "
            "Did you back up pages.jsonl before the Surya recovery run?"
        )
    if not surya_path.exists():
        raise FileNotFoundError(f"Missing Surya output: {surya_path}")

    sonnet_rows = _load_jsonl(sonnet_path)
    surya_rows = _load_jsonl(surya_path)
    merged = merge_rows(sonnet_rows, surya_rows)

    summary = {
        "card_id": card_id,
        "sonnet_pages": len(sonnet_rows),
        "surya_pages_total": len(surya_rows),
        "merged_total": len(merged),
        "surya_pages_kept": len(merged) - len(sonnet_rows),
    }

    if dry_run:
        return summary

    _write_jsonl_atomic(surya_path, merged)
    if meta_path.exists():
        _update_meta(meta_path, len(merged), len(sonnet_rows))
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--card-id", action="append", required=True,
        help="Card id to merge. Pass repeatedly for multiple cards.",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    failures: list[tuple[str, str]] = []
    for cid in args.card_id:
        try:
            summary = merge_card(cid, dry_run=args.dry_run)
            print(
                f"{cid}: merged {summary['merged_total']} pages "
                f"({summary['sonnet_pages']} sonnet + "
                f"{summary['surya_pages_kept']} surya)"
            )
        except Exception as exc:  # noqa: BLE001
            failures.append((cid, f"{type(exc).__name__}: {exc}"))
            print(f"{cid}: FAILED — {failures[-1][1]}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
