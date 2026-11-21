"""Run tallies and exit-code outcomes for ``r2_archive_assets.py``.

``RunState`` carries one run's counts and budget result; ``full_hash_outcome``,
``drift_outcome`` and ``staleness_outcome`` turn it into the exit code and the
complete-run record. Imported by ``r2_archive_assets.py`` after its bootstrap.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pursue_index.byte_dispositions import RESAVE_CONTENT_VERIFIED

RUN_RECORD_NAME = "full-hash-runs.jsonl"
RUN_RECORD_SCHEMA = "pursue-full-hash-run/v1"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RunState:
    """Per-run tallies shared by ``_process_card`` and ``main``."""

    full_hash: bool = False
    bytes_hashed: int = 0
    # (card_id, old_sha, new_sha) for each card that already had registry rows
    # and now has a row whose bytes differ from the LATEST row (a revert to an
    # earlier row's bytes counts: the latest is what was published last).
    drift: list[tuple[str, str, str]] = field(default_factory=list)
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "new": 0, "unchanged": 0, "head-unchanged": 0, "archive-hit": 0, "fail": 0,
        }
    )
    over_budget: bool = False
    unhashed: int = 0
    partial_reason: str = ""  # why a run covered fewer cards than the manifest has
    cards_hashed: int = 0
    no_upstream_url: int = 0


def write_run_record(path: Path, entry: dict[str, Any]) -> None:
    """Append one complete-run record (one JSON object per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def full_hash_outcome(args, state: RunState) -> int:
    """Exit code for a ``--full-hash`` run; writes the complete-run record on success."""
    if state.over_budget:
        print(
            f"[r2-archive] FULL-HASH FAILED: byte budget {args.max_bytes_per_run} exceeded "
            f"after {state.bytes_hashed} bytes; {state.unhashed} card(s) left unhashed. "
            "No complete-run record written.",
            file=sys.stderr,
        )
        return 1
    fails = state.counts["fail"]
    if fails or state.partial_reason:
        why = f"{fails} card(s) failed to fetch" if fails else state.partial_reason
        print(
            f"[r2-archive] FULL-HASH INCOMPLETE: {why}. No complete-run record written.",
            file=sys.stderr,
        )
        return 1
    if not args.dry_run:
        write_run_record(
            args.run_record or args.registry.parent / RUN_RECORD_NAME,
            {
                "schema": RUN_RECORD_SCHEMA,
                "completed_at": now_iso(),
                "cards_hashed": state.cards_hashed,
                "bytes_hashed": state.bytes_hashed,
                "drift_count": len(state.drift),
                "no_upstream_url": state.no_upstream_url,
            },
        )
    return 0


def newest_complete_run(path: Path, now: datetime | None = None) -> datetime | None:
    """Newest ``completed_at`` in the run records; junk lines and future dates are ignored."""
    now = now or datetime.now(UTC)
    newest: datetime | None = None
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        try:
            when = datetime.fromisoformat(json.loads(line)["completed_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > now + timedelta(minutes=5):
            continue  # a record dated in the future is not evidence of a past run
        if newest is None or when > newest:
            newest = when
    return newest


def staleness_outcome(args) -> int:
    """1 when the weekly full-hash record is missing or older than the allowed age."""
    if args.max_full_hash_age_days is None or args.full_hash:
        return 0
    path = args.run_record or args.registry.parent / RUN_RECORD_NAME
    newest = newest_complete_run(path)
    if newest is None:
        print(
            f"[r2-archive] STALE: no complete full-hash run on record in {path}",
            file=sys.stderr,
        )
        return 1
    age = datetime.now(UTC) - newest
    if age > timedelta(days=args.max_full_hash_age_days):
        print(
            f"[r2-archive] STALE: the newest complete full-hash run finished "
            f"{newest.isoformat()}, {age.days} days ago "
            f"(more than {args.max_full_hash_age_days} days)",
            file=sys.stderr,
        )
        return 1
    return 0


def drift_outcome(args, state: RunState, dispositions) -> int:
    """1 when ``--fail-on-drift`` and a drifted card has no covering disposition."""
    if not args.fail_on_drift:
        return 0
    uncovered = []
    for card_id, old, new in state.drift:
        disp = dispositions.get((card_id, new))
        if disp is not None and disp.disposition == RESAVE_CONTENT_VERIFIED:
            print(f"[r2-archive] drift covered by a disposition: {card_id} {old} -> {new}")
        else:
            uncovered.append((card_id, old, new))
    for card_id, old, new in uncovered:
        print(
            f"[r2-archive] BYTE DRIFT: {card_id} old sha {old} -> new sha {new} "
            "(no resave-content-verified disposition covers it)",
            file=sys.stderr,
        )
    return 1 if uncovered else 0
