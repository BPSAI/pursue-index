"""Stale-edge guard state for the tranche poll (#157).

Cache edges in front of the upstream CSV have served superseded copies for
days after a change, and a re-encoded variant of the new copy alongside
it. Each flip used to be recorded as an upstream change. The guard keeps
just enough history in ``data/poll-state.json`` (committed next to
``last-known-csv-sha.txt``) to tell those apart:

* ``seen``: every sha the poll has observed, oldest first. A sha listed
  before the current one is a *stale-edge* observation unless its
  ``Last-Modified`` is strictly newer than the current sha's.
* ``current_last_modified``: the ``Last-Modified`` the current sha was
  served with, for that comparison.
* ``pending``: a sha seen once but not yet confirmed. A change is declared
  only after two consecutive sightings of the same new sha; observations
  of the current sha or of stale shas in between don't break the streak,
  because stale edges serving those are exactly the noise being filtered.

When the file is missing the guard fails closed: every sha already in the
byte archive counts as seen before the current one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal

from pursue_index.scrape.encoding_equivalence import is_encoding_only_change

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")

Observation = Literal["current", "stale", "candidate"]


@dataclass
class GuardState:
    current_sha: str
    current_last_modified: str | None = None
    pending: dict[str, str | None] | None = None
    seen: list[str] = field(default_factory=list)

    @property
    def pending_sha(self) -> str | None:
        return self.pending.get("sha") if self.pending else None

    def classify(self, sha: str, last_modified: str | None) -> Observation:
        """Is a fetched ``sha`` the current one, a stale edge, or a candidate?"""
        if sha == self.current_sha:
            return "current"
        seen_before = sha in self.seen and self.seen.index(sha) < self.seen.index(self.current_sha)
        if seen_before and not is_strictly_newer(last_modified, self.current_last_modified):
            return "stale"
        return "candidate"

    def observe(self, sha: str) -> None:
        if sha not in self.seen:
            self.seen.append(sha)

    def set_pending(self, sha: str, last_modified: str | None, ts: str) -> None:
        if self.pending_sha != sha:
            self.pending = {"sha": sha, "last_modified": last_modified, "first_seen_at": ts}

    def promote(self, sha: str, last_modified: str | None) -> None:
        """``sha`` becomes current; everything seen so far now precedes it."""
        self.seen = [s for s in self.seen if s != sha] + [sha]
        self.current_sha = sha
        self.current_last_modified = last_modified
        self.pending = None

    def confirm_by_refetch(
        self,
        sha: str,
        last_modified: str | None,
        again: tuple[str, str | None] | None,
        ts: str,
    ) -> bool:
        """Did an immediate re-fetch (``(sha, Last-Modified)``, or ``None``
        if it failed) see ``sha`` again?

        On disagreement the latest new sha becomes pending: a re-fetch
        landing on the current or a stale sha keeps ``sha`` pending, a
        different new sha replaces it, and a failed re-fetch leaves the
        confirmation to the next run.
        """
        if again is not None:
            sha2, lm2 = again
            if sha2 == sha:
                return True
            if self.classify(sha2, lm2) == "candidate":
                self.observe(sha2)
                self.set_pending(sha2, lm2, ts)
                return False
        self.set_pending(sha, last_modified, ts)
        return False

    def learn_last_modified(self, last_modified: str | None) -> bool:
        """Record the current sha's ``Last-Modified`` if not yet known."""
        if self.current_last_modified or not last_modified:
            return False
        self.current_last_modified = last_modified
        return True

    def to_json(self) -> str:
        payload = {
            "current_sha": self.current_sha,
            "current_last_modified": self.current_last_modified,
            "pending": self.pending,
            "seen": self.seen,
        }
        return json.dumps(payload, indent=2) + "\n"


def encoding_only_vs_archive(archive_dir: Path | None, old_sha: str, body: bytes) -> bool:
    """Is ``body`` an encoding-only change from the archived ``old_sha``?

    Fails closed: without the prior bytes, or when ``old_sha`` (read from
    repo files) isn't a 64-hex sha fit to name an archive path, the change
    counts as real.
    """
    if archive_dir is None or not _SHA256_HEX.fullmatch(old_sha):
        return False
    prior = archive_dir / f"{old_sha}.csv"
    if not prior.exists():
        return False
    return is_encoding_only_change(prior.read_bytes(), bytes(body))


def parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def is_strictly_newer(candidate: str | None, current: str | None) -> bool:
    """True only when both headers parse and ``candidate`` is later."""
    a, b = parse_http_date(candidate), parse_http_date(current)
    return a is not None and b is not None and a > b


def _archived_shas(archive_dir: Path | None) -> list[str]:
    if archive_dir is None or not archive_dir.is_dir():
        return []
    return sorted(p.stem for p in archive_dir.glob("*.csv"))


def load_guard(path: Path, current_sha: str, archive_dir: Path | None) -> GuardState:
    """Load the guard for ``current_sha`` (the authoritative last-known sha).

    A guard written for a different current sha (e.g. the sha file was
    edited by hand) keeps its history but forgets the stale
    ``Last-Modified``. A missing or unreadable file is seeded from the
    byte archive.
    """
    data = _read_json(path)
    if data is None:
        seen = [s for s in _archived_shas(archive_dir) if s != current_sha]
        return GuardState(current_sha=current_sha, seen=[*seen, current_sha] if current_sha else seen)
    seen = [s for s in data.get("seen", []) if isinstance(s, str)]
    same_current = data.get("current_sha") == current_sha
    pending = data.get("pending") if isinstance(data.get("pending"), dict) else None
    if pending and pending.get("sha") == current_sha:
        pending = None
    guard = GuardState(
        current_sha=current_sha,
        current_last_modified=data.get("current_last_modified") if same_current else None,
        pending=pending,
        seen=seen,
    )
    if current_sha:
        guard.observe(current_sha)
    return guard


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_guard(path: Path, guard: GuardState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(guard.to_json(), encoding="utf-8")
