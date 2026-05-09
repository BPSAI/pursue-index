"""GitHub Actions IO helpers extracted from ``poll_pursue.py``.

Kept in a sibling module (and prefixed ``_``) so:

* The main script stays under the 200-line warning threshold.
* These pure-IO helpers can be unit-tested without spinning up the
  full poll loop.
* The workflow-output contract lives in one place — anything that
  touches ``$GITHUB_OUTPUT`` formatting or issue-body shaping is here.

No business logic in this module: the poll/diff decision lives in
``poll_pursue.poll()``. We only know how to *render* a result for the
runner.
"""

from __future__ import annotations

import os
import uuid
from typing import Protocol

# Cap published exception strings at this length. Long ``repr`` outputs
# can carry interpolated URLs (with credentials), file paths, or env
# values that would otherwise leak straight into a public issue body.
# 500 chars is enough for an HTTP status + headline message, not enough
# for a full traceback. (SEC-003)
ERROR_MAX_LEN = 500


def truncate_error(message: str, *, limit: int = ERROR_MAX_LEN) -> str:
    """Trim ``message`` to ``limit`` characters, appending an ellipsis
    marker so consumers can tell truncation happened.
    """
    if len(message) <= limit:
        return message
    # Reserve room for the truncation marker so the total stays <= limit.
    marker = "...[truncated]"
    keep = max(limit - len(marker), 0)
    return message[:keep] + marker


def changed_issue_body(old_sha: str, new_sha: str, ts: str, bootstrap: bool) -> str:
    """Issue body for the ``tranche-detected`` path."""
    if bootstrap:
        return (
            "First observation of upstream CSV. Recording sha for future"
            f" change detection.\n\n* new_sha: `{new_sha}`\n"
            f"* observed_at: {ts}\n"
        )
    return (
        "Upstream PURSUE CSV changed. The operator should run the heavy"
        " ingest pipeline (`pursue scrape run` -> download -> ocr -> embed).\n\n"
        f"* old_sha: `{old_sha}`\n"
        f"* new_sha: `{new_sha}`\n"
        f"* observed_at: {ts}\n"
    )


def failed_issue_body(error: str, ts: str) -> str:
    """Issue body for the ``tranche-poll-failure`` path."""
    return (
        "Polling the upstream CSV failed. This may indicate Akamai has"
        " changed defenses, the upstream is down, or our curl_cffi"
        " impersonation has drifted. Investigate before assuming the"
        " corpus is stable.\n\n"
        f"* error: {error}\n"
        f"* observed_at: {ts}\n"
    )


class _UnchangedLike(Protocol):
    sha: str


class _ChangedLike(Protocol):
    old_sha: str
    new_sha: str
    is_bootstrap: bool
    issue_labels: tuple[str, ...]
    issue_body: str


class _FailedLike(Protocol):
    error: str
    issue_labels: tuple[str, ...]
    issue_body: str
    extra: dict[str, str]


def _heredoc_delimiter() -> str:
    """Generate a one-shot heredoc delimiter that no realistic issue
    body line could match. Per GH docs, the recommended pattern.

    Random suffix so a future ``EOF`` line in the body cannot
    terminate the heredoc early.
    """
    return f"EOF_{uuid.uuid4().hex}"


def _emit_unchanged(result: _UnchangedLike) -> list[str]:
    return ["status=unchanged", f"new_sha={result.sha}"]


def _emit_changed(result: _ChangedLike) -> list[str]:
    delim = _heredoc_delimiter()
    return [
        "status=changed",
        f"old_sha={result.old_sha}",
        f"new_sha={result.new_sha}",
        f"is_bootstrap={'true' if result.is_bootstrap else 'false'}",
        f"issue_labels={','.join(result.issue_labels)}",
        f"issue_title=PURSUE tranche detected: {result.new_sha[:12]}",
        f"issue_body<<{delim}",
        result.issue_body.rstrip("\n"),
        delim,
    ]


def _emit_failed(result: _FailedLike) -> list[str]:
    delim = _heredoc_delimiter()
    lines = [
        "status=failed",
        f"error={result.error}",
        f"issue_labels={','.join(result.issue_labels)}",
        "issue_title=PURSUE poll failed",
        f"issue_body<<{delim}",
        result.issue_body.rstrip("\n"),
        delim,
    ]
    # Surface any structured diagnostics the poll captured (exception
    # type at minimum). Single-line key=value pairs only — the heredoc
    # is reserved for the issue body.
    for key, value in sorted(result.extra.items()):
        # Force single-line so we never accidentally insert a heredoc
        # terminator inside a key=value pair.
        flat = str(value).replace("\n", " ").strip()
        lines.append(f"extra_{key}={flat}")
    return lines


def emit_gh_outputs(result: object) -> None:
    """Write step-output kv pairs to ``$GITHUB_OUTPUT`` (if set).

    Accepts any of the three result variants from ``poll_pursue``;
    dispatches by attribute presence rather than importing the dataclass
    types (avoids a circular import / coupling).
    """
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    if hasattr(result, "old_sha") and hasattr(result, "new_sha"):
        lines = _emit_changed(result)  # type: ignore[arg-type]
    elif hasattr(result, "error"):
        lines = _emit_failed(result)  # type: ignore[arg-type]
    else:
        lines = _emit_unchanged(result)  # type: ignore[arg-type]
    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
