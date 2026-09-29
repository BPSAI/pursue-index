"""Discriminated-union result types for the upstream poll.

Lives in its own module so ``poll_pursue.py`` stays under the 200-line
warning threshold. The frozen dataclasses pin the
contract between ``poll()`` and the workflow's ``$GITHUB_OUTPUT``
serializer in ``_poll_gh_io.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar


@dataclass(frozen=True)
class Unchanged:
    """The upstream sha matches the last-known sha."""

    sha: str


@dataclass(frozen=True)
class Changed:
    """The upstream sha differs from last-known (or there is no last-known)."""

    old_sha: str
    new_sha: str
    fetched_at: str
    is_bootstrap: bool = False
    issue_labels: tuple[str, ...] = ("tranche-detected",)
    issue_body: str = ""


@dataclass(frozen=True)
class Failed:
    """The fetch raised, returned non-200, or returned an empty body."""

    error: str
    fetched_at: str
    issue_labels: tuple[str, ...] = ("tranche-poll-failure",)
    issue_body: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Stale:
    """A sha seen before the current one, without a newer ``Last-Modified``.

    A stale cache edge, not an upstream change: nothing is committed.
    """

    status: ClassVar[str] = "stale"
    sha: str
    current_sha: str
    last_modified: str | None = None


@dataclass(frozen=True)
class Pending:
    """A new sha seen once; declared only if the next sighting agrees."""

    status: ClassVar[str] = "pending"
    sha: str
    current_sha: str
    fetched_at: str


@dataclass(frozen=True)
class Benign:
    """A confirmed change that only re-encodes the same text: last-known
    moves, but no tranche is declared."""

    status: ClassVar[str] = "benign"
    old_sha: str
    new_sha: str
    fetched_at: str


PollResult = Unchanged | Changed | Failed | Stale | Pending | Benign
