"""Where the registry drift scan starts and what it covers, for ``r2_archive_assets.py``.

The window starts at the earliest of the last passing gate marker and the last complete
``--full-hash`` run; a marker also records the ids of the registry rows its gate covered, so the
next scan skips exactly those rows, wherever they sit in the file. Imported by ``r2_archive_assets.py`` after its bootstrap.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _r2_hosts import type_change_line
from _r2_registry import group_registry, load_registry_rows
from _r2_run_state import (
    BOOTSTRAP_WINDOW_DAYS,
    GATE_MARKER_NAME,
    RUN_RECORD_NAME,
    newest_complete_run,
)

from pursue_index.asset_rows import rows_of_asset, type_change


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


def row_id(row: dict[str, Any]) -> str:
    """A stable id for a registry row: the registry has no unique field of its own, so it is
    derived from the row's content (sha256 of its canonical JSON, first 20 hex digits)."""
    canon = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:20]


def gated_row_ids(args, now: datetime | None = None) -> set[str] | None:
    """Ids of the registry rows the newest passing gate covered, or ``None`` when that marker
    is missing, unreadable or in the old integer format (then the whole window is rescanned)."""
    now = now or datetime.now(UTC)
    path = gate_marker_path(args)
    if not path.exists():
        return None
    newest: datetime | None = None
    ids: set[str] | None = None
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
        listed = row.get("gated_row_ids")
        ok = isinstance(listed, list) and all(isinstance(i, str) for i in listed)
        newest, ids = when, set(listed) if ok else None
    return ids


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


def drift_and_coverage(
    registry: dict[str, list[dict[str, Any]]],
    since: datetime,
    rows_after: list[dict[str, Any]] | None = None,
):
    """The one place a registry row is evaluated, and so the only producer of covered ids.

    Returns ``(drift, covered, skipped)``. ``drift`` is ``(card_id, previous_sha, new_sha)``
    for each row fetched at/after ``since`` whose sha differs from the previous row of the
    same card AND the same ``asset_url``, or (for a moved URL) the newest earlier row of the
    same file type. A first row with no such earlier row is net-new, never drift (one whose
    file type changed with its URL is printed as a ``TYPE CHANGE`` warning).

    ``covered`` holds the ids of exactly the rows whose comparison ran (``when >= since``).
    ``skipped`` maps the id of each row looked at but not evaluated to ``(card_id, reason)``:
    ``"outside the window"`` or ``"unparseable time"``.

    ``rows_after`` (row objects of ``registry``, as ``load_registry`` returns them) limits the
    scan to those rows: the ones a passing gate has not covered yet. ``None`` scans them all."""
    fresh = None if rows_after is None else {id(r) for r in rows_after}
    out: list[tuple[str, str, str]] = []
    covered: set[str] = set()
    skipped: dict[str, tuple[str, str]] = {}
    for card_id, rows in registry.items():
        for i, row in enumerate(rows):
            if fresh is not None and id(row) not in fresh:
                continue
            try:
                when = datetime.fromisoformat(row["fetched_at"])
            except (KeyError, ValueError, TypeError):
                skipped[row_id(row)] = (card_id, "unparseable time")
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when < since:
                skipped[row_id(row)] = (card_id, "outside the window")
                continue
            covered.add(row_id(row))
            earlier = rows_of_asset(rows[:i], row.get("asset_url"), row.get("asset_filename"))
            prev = earlier[-1] if earlier else None
            if prev is None:
                change = type_change(rows[:i], row.get("asset_url"), row.get("asset_filename"))
                if change and not any(
                    r.get("asset_url") == change[0].get("asset_url") for r in rows[i + 1 :]
                ):
                    print(type_change_line(card_id, *change, row.get("asset_url")))
                continue
            old, new = prev.get("byte_sha256"), row.get("byte_sha256")
            if old and new and old != new:
                out.append((card_id, old, new))
    return out, covered, {k: v for k, v in skipped.items() if k not in covered}


def registry_drift_since(
    registry: dict[str, list[dict[str, Any]]],
    since: datetime,
    rows_after: list[dict[str, Any]] | None = None,
):
    """The drift list of ``drift_and_coverage`` (see there)."""
    return drift_and_coverage(registry, since, rows_after)[0]


def _report_ungated(skipped: dict[str, tuple[str, str]]) -> None:
    """One line: how many rows stay ungated, why, and the first few card ids."""
    if not skipped:
        return
    groups: dict[str, list[str]] = {}
    for card_id, reason in skipped.values():
        groups.setdefault(reason, []).append(card_id)
    parts = [
        f"{len(cards)} {reason} (e.g. {', '.join(sorted(set(cards))[:3])})"
        for reason, cards in sorted(groups.items())
    ]
    print(f"[r2-archive] {len(skipped)} registry rows left ungated: " + "; ".join(parts))


def scan_registry(args, since: datetime, gated: set[str] | None) -> tuple[Any, list[str]]:
    """``(drift rows, ids for the next gate marker)``.

    ``gated`` ids (``None`` scans every row) are skipped wherever they sit and stay covered
    while still in the registry; the only other ids are those ``drift_and_coverage`` evaluated.
    Rows it skipped stay ungated and are reported."""
    if not args.fail_on_drift:
        return (), []
    rows = load_registry_rows(args.registry)
    ids = [row_id(r) for r in rows]
    present = set(ids)
    keep = set() if gated is None else gated & present
    after = None if gated is None else [r for r, i in zip(rows, ids, strict=True) if i not in gated]
    drift, covered, skipped = drift_and_coverage(group_registry(rows), since, after)
    _report_ungated({k: v for k, v in skipped.items() if k not in keep})
    return drift, sorted(keep | covered)
