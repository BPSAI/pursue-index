#!/usr/bin/env python3
"""Build ``web/public/data/asr-diff-bundle.json`` from per-row
``asr_diff.jsonl`` sidecars (R7C.27).

``pursue_index.transcribe.asr_diff_runner.run_row`` writes one sidecar row
per ``(card_id, row_key)`` next to the transcript it diffs, on the NAS.
This script rolls those up to one entry per card -- the WORST status
across a card's rows, since one row flagged for review means the card
isn't clear even if its other rows agreed completely -- and writes the
committed bundle ``scripts/build_qc_coverage.py`` reads, the same publish
step ``clean-qc-bundle.json`` already uses.

Usage::

    python scripts/build_asr_diff_bundle.py --cards aud1,aud2,...
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json

from pursue_index import get_logger
from pursue_index.card_id import InvalidCardIdError, require_card_ids
from pursue_index.paths import repo_root
from pursue_index.transcribe import asr_diff_sidecar as sidecar
from pursue_index.transcribe.asr_diff import derive_status, effective_threshold

log = get_logger(__name__)

REPO_ROOT = repo_root()

DEFAULT_OUT = REPO_ROOT / "web" / "public" / "data" / "asr-diff-bundle.json"

# A row's status is "judged" or "review"; review wins any tie, since the
# whole point is to never hide a disagreement a human should see.
_STATUS_RANK = {"judged": 0, "review": 1}


def _row_evidence(row: dict) -> tuple[object, object, object]:
    """``(agreement, threshold, min_words)`` for one sidecar row."""
    wa, wb = row.get("word_count_a"), row.get("word_count_b")
    words = min(wa, wb) if isinstance(wa, int) and isinstance(wb, int) else None
    return row.get("agreement"), effective_threshold(row.get("threshold")), words


def _card_entry(
    card_id: str, rows: dict[str, dict], expected: set[str] | None,
    version: str | None, pages_digest: str | None = None,
) -> dict | None:
    """One card's entry: the WORST re-derived row (lowest agreement wins).

    Only rows the card's ``meta.json`` lists count (a stale sidecar row for a
    vanished row key is ignored), and only rows compared against the card's
    CURRENT transcript version and pages digest: a row from before a
    re-transcription or a pages change saw different text and counts as uncompared. A card with an uncompared row, or with no
    readable meta, never graduates: it gets an entry only when a compared
    row already needs human review, so a disagreement is never hidden.
    """
    if expected is None:
        return None
    rows = {
        k: r for k, r in rows.items()
        if k in expected and version is not None and r.get("transcript_version") == version
        and pages_digest is not None and r.get("pages_digest") == pages_digest
    }
    if not rows:
        return None
    worst = None
    for row in rows.values():
        agreement, threshold, words = _row_evidence(row)
        status = derive_status(agreement, threshold, words)
        rank = (_STATUS_RANK[status], -(agreement if isinstance(agreement, (int, float)) else -1.0))
        if worst is None or rank > worst[0]:
            worst = (rank, status, agreement, threshold, words)
    _, status, agreement, threshold, words = worst
    if status == "judged" and expected - rows.keys():
        return None
    return {
        "card_id": card_id, "status": status, "agreement": agreement,
        "threshold": threshold, "min_words": words, "pages_digest": pages_digest,
    }


def build(*, ocr_dir: Path, card_ids: list[str]) -> dict:
    """``{"cards": [...]}`` for every card with a completed comparison, sorted
    by card_id. ``card_id`` is validated before it is joined into a path."""
    cards = []
    for card_id in require_card_ids(card_ids):
        card_dir = ocr_dir / card_id
        rows = sidecar.load_existing(card_dir / sidecar.SIDECAR_FILE)
        expected = sidecar.expected_row_keys(sidecar.read_meta(card_dir))
        entry = _card_entry(
            card_id, rows, expected, sidecar.transcript_version(card_dir),
            sidecar.card_pages_digest(card_dir),
        )
        if entry is not None:
            cards.append(entry)
    cards.sort(key=lambda c: c["card_id"])
    return {"cards": cards}


def merge_bundles(existing: dict, new: dict, *, requested: list[str]) -> dict:
    """``existing`` with every ``requested`` card replaced by ``new``'s verdict.

    A rebuild for a few cards must not drop the verdicts already published
    for the others; a requested card that no longer qualifies is removed.
    """
    asked = set(requested)
    kept = [
        c for c in existing.get("cards", [])
        if isinstance(c, dict) and c.get("card_id") not in asked
    ]
    cards = sorted([*kept, *new["cards"]], key=lambda c: c["card_id"])
    return {"cards": cards}


def _load_published(path: Path) -> dict:
    """The bundle already at ``path``, or an empty one when absent/unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cards": []}
    return data if isinstance(data, dict) else {"cards": []}


def as_status_map(bundle: dict) -> dict[str, str]:
    """``{card_id: status}`` -- what ``build_qc_coverage.py`` passes to
    ``build_coverage``. The published status is NOT trusted: ``judged`` is
    re-derived from the card's agreement, threshold and word count, and any
    status other than ``judged``/``review`` becomes ``review`` (logged)."""
    out: dict[str, str] = {}
    for c in bundle["cards"]:
        if not isinstance(c, dict) or not isinstance(c.get("card_id"), str):
            log.warning("asr_diff.bundle.bad_entry", entry=str(c)[:60])
            continue
        published = c.get("status")
        derived = derive_status(
            c.get("agreement"), effective_threshold(c.get("threshold")), c.get("min_words"),
        )
        if published not in _STATUS_RANK:
            log.warning("asr_diff.bundle.bad_status", card_id=c.get("card_id"), status=str(published)[:40])
            derived = "review"
        elif published != derived:
            log.warning("asr_diff.bundle.status_mismatch", card_id=c.get("card_id"),
                        published=published, derived=derived)
        out[c["card_id"]] = "review" if "review" in (published, derived) else "judged"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ocr-dir", type=Path, default=None,
        help="Transcript sidecar root (default: settings.ocr_dir).",
    )
    parser.add_argument(
        "--cards", required=True,
        help="Comma-separated AUD card_ids to roll up.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.ocr_dir is None:
        from pursue_index.config import settings
        ocr_dir = settings.ocr_dir
    else:
        ocr_dir = args.ocr_dir
    card_ids = [c.strip() for c in args.cards.split(",") if c.strip()]

    try:
        bundle = build(ocr_dir=ocr_dir, card_ids=card_ids)
    except InvalidCardIdError as exc:
        print(f"asr-diff-bundle: {exc}", file=sys.stderr)
        return 2
    bundle = merge_bundles(_load_published(args.out), bundle, requested=card_ids)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"asr-diff-bundle: {len(bundle['cards'])} card(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
