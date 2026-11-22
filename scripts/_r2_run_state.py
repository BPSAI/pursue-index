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

from _r2_hosts import host_of

from pursue_index.asset_rows import file_type, rows_of_asset, type_change  # noqa: F401
from pursue_index.byte_dispositions import RESAVE_CONTENT_VERIFIED

RUN_RECORD_NAME = "full-hash-runs.jsonl"
RUN_RECORD_SCHEMA = "pursue-full-hash-run/v1"
# Written by a --fail-on-drift run (daily or weekly) whose drift gate passed; its
# ``completed_at`` is the START of that run, so the next gate rescans from there.
GATE_MARKER_NAME = "drift-gate-passes.jsonl"
GATE_MARKER_SCHEMA = "pursue-drift-gate-pass/v1"
BOOTSTRAP_WINDOW_DAYS = 8


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def bootstrap_start(now: datetime) -> str:
    """The scan start used when a run's own start is unknown: the whole bootstrap window."""
    return (now - timedelta(days=BOOTSTRAP_WINDOW_DAYS)).isoformat()


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
    # Hosts of the manifest's asset URLs plus the approved list; every fetch and redirect
    # must stay inside it.
    allowed_hosts: frozenset[str] = frozenset()
    size_alerts: int = 0  # assets past the x2 growth cap (alerts, not failures)
    started_at: str = ""  # when the run began; recorded so a rescan can start before its rows
    byte_budget: int | None = None  # ``--max-bytes-per-run``; caps each fetch's ceiling
    budget_hit: bool = False  # a fetch stopped at the budget left, not at its own ceiling
    card_urls: dict[str, set[str]] = field(default_factory=dict)  # asset URLs per manifest card

    def fetch_ceiling(self, ceiling: int) -> int:
        """``ceiling``, cut to what is left of the run's byte budget when there is one."""
        if self.byte_budget is None:
            return ceiling
        return min(ceiling, max(self.byte_budget - self.bytes_hashed, 0))

    def note_type_change(self, card_id: str, card_rows, asset_url: Any, asset_filename: Any) -> None:
        """Warn when an asset's URL and file type both changed (its old asset is gone from the manifest)."""
        found = type_change(card_rows, asset_url, asset_filename)
        if found and str(found[0].get("asset_url")) not in self.card_urls.get(card_id, ()):
            print(type_change_line(card_id, *found, asset_url))

    def note_growth(self, card_id: str, known: int | None, size: int, cap: int) -> None:
        """Alert, without failing the card, when an asset with a known size passed its cap."""
        if isinstance(known, int) and known > 0 and size > cap:
            self.size_alerts += 1
            print(f"[r2-archive] SIZE ALERT: {card_id} {known} -> {size} (over the 2x growth cap)")


def type_change_line(card_id: str, prev: dict[str, Any], old: str, new: str, new_url: Any) -> str:
    """The warning for an asset whose file type changed along with its URL (not a drift failure)."""
    return (
        f"[r2-archive] TYPE CHANGE: {card_id} {old} -> {new} "
        f"({host_of(prev.get('asset_url'))} -> {host_of(new_url)})"
    )


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
        done = datetime.now(UTC)
        write_run_record(
            args.run_record or args.registry.parent / RUN_RECORD_NAME,
            {
                "schema": RUN_RECORD_SCHEMA,
                "started_at": state.started_at or bootstrap_start(done),
                "completed_at": done.isoformat(),
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


def gate_marker_path(args) -> Path:
    return args.gate_marker or args.registry.parent / GATE_MARKER_NAME


def newest_run_start(path: Path, now: datetime | None = None) -> datetime | None:
    """When the newest complete run in ``path`` BEGAN.

    A complete weekly record is written whether or not its drift gate passed, and the
    rows it wrote are dated inside the run, before ``completed_at``. Only ``started_at``
    is safe as a scan start. A legacy record without one is not trusted: it yields the
    bootstrap window instead, which reaches at least as far back."""
    now = now or datetime.now(UTC)
    finished = newest_complete_run(path, now)
    if finished is None:
        return None
    started: datetime | None = None
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
            done = datetime.fromisoformat(row["completed_at"])
            when = datetime.fromisoformat(row["started_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if done.tzinfo is None:
            done = done.replace(tzinfo=UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if done == finished:
            started = when
    if started is None:
        return min(finished, now - timedelta(days=BOOTSTRAP_WINDOW_DAYS))
    return started


def gated_row_count(args, now: datetime | None = None) -> int | None:
    """Registry rows (in file order) the newest passing gate covered, or ``None`` when that
    marker is missing or in the old format (then the whole window is rescanned)."""
    now = now or datetime.now(UTC)
    path = gate_marker_path(args)
    if not path.exists():
        return None
    newest: datetime | None = None
    count: int | None = None
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
            when = datetime.fromisoformat(row["completed_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > now + timedelta(minutes=5) or (newest is not None and when <= newest):
            continue
        rows = row.get("gated_rows")
        newest, count = when, rows if isinstance(rows, int) and not isinstance(rows, bool) and rows >= 0 else None
    return count


def drift_window_start(args, now: datetime | None = None) -> datetime:
    """Where the registry drift scan starts: the EARLIEST of the last passing gate marker
    and the start of the last complete ``--full-hash`` run.

    The weekly record exists even when that run's drift gate failed, so a run with no
    marker must not start after the rows it wrote. With neither, the last 8 days."""
    now = now or datetime.now(UTC)
    record = args.run_record or args.registry.parent / RUN_RECORD_NAME
    starts = [
        t
        for t in (newest_complete_run(gate_marker_path(args), now), newest_run_start(record, now))
        if t is not None
    ]
    return min(starts) if starts else now - timedelta(days=BOOTSTRAP_WINDOW_DAYS)


def registry_drift_since(
    registry: dict[str, list[dict[str, Any]]],
    since: datetime,
    rows_after: list[dict[str, Any]] | None = None,
):
    """``(card_id, previous_sha, new_sha)`` for each row fetched at/after ``since`` whose sha
    differs from the previous row of the same card AND the same ``asset_url``, or
    (for a moved URL) the newest earlier row of the same file type. A first row with no
    such earlier row is net-new, never drift (one whose file type changed with its URL is
    printed as a ``TYPE CHANGE`` warning).

    ``rows_after`` (row objects of ``registry``, as ``load_registry`` returns them) limits the
    scan to those rows: the ones a passing gate has not covered yet. ``None`` scans them all."""
    fresh = None if rows_after is None else {id(r) for r in rows_after}
    out = []
    for card_id, rows in registry.items():
        for i, row in enumerate(rows):
            if fresh is not None and id(row) not in fresh:
                continue
            try:
                when = datetime.fromisoformat(row["fetched_at"])
            except (KeyError, ValueError, TypeError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            earlier = rows_of_asset(rows[:i], row.get("asset_url"), row.get("asset_filename"))
            prev = earlier[-1] if earlier else None
            if prev is None:
                change = type_change(rows[:i], row.get("asset_url"), row.get("asset_filename"))
                if change and when >= since and not any(
                    r.get("asset_url") == change[0].get("asset_url") for r in rows[i + 1 :]
                ):
                    print(type_change_line(card_id, *change, row.get("asset_url")))
                continue
            old, new = prev.get("byte_sha256"), row.get("byte_sha256")
            if when >= since and old and new and old != new:
                out.append((card_id, old, new))
    return out


def drift_outcome(args, state: RunState, dispositions, registry_drift=()) -> int:
    """1 when ``--fail-on-drift`` and a drifted card has no covering disposition.

    ``registry_drift`` is the registry scan (rows any lane appended since the previous
    complete run); it is merged with what this run detected itself."""
    if not args.fail_on_drift:
        return 0
    uncovered = []
    for card_id, old, new in dict.fromkeys([*state.drift, *registry_drift]):
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
