"""Promote-and-build path for ``pursue ingest run`` (R7C.2 / #169).

Split out of ``ingest_cli.py`` to keep ``run_cmd`` a thin handler: gate
the tranche, locate its approved snapshot, and -- for a real (non-dry)
run -- promote it to every deploy-side surface and run the operator-local
poster/thumb builders. ``run_cmd`` only calls `promote_and_report` when
``--dry-run`` is absent, so a dry run never reaches any of this.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pursue_index.ingest import is_tranche_approved
from pursue_index.ingest_run import locate_snapshot, promote_snapshot
from pursue_index.paths import UntrustedRootError, repo_root
from pursue_index.poll_freshness import (
    BehindPollerError,
    PollCheckError,
    refuse_if_behind,
    require_reason,
)


def enforce_poll_freshness(
    allow_behind: bool, reason: str | None, tranche_sha: str | None = None,
) -> None:
    """Refuse the calling command if this checkout is behind origin/main on
    the paths the poller writes, or if that cannot be determined. See
    `pursue_index.poll_freshness`."""
    if allow_behind:
        try:
            reason = require_reason(reason)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
    this_repo_root = _resolve_root_or_exit()
    try:
        refuse_if_behind(
            this_repo_root,
            allow_behind=allow_behind,
            reason=reason,
            audit_log=this_repo_root / "data" / "poll-behind-audit-log.jsonl",
            tranche_sha=tranche_sha,
        )
    except BehindPollerError as exc:
        typer.echo(
            f"refusing — {exc}. Use --allow-behind --reason <text> to override.",
            err=True,
        )
        raise typer.Exit(4) from exc
    except PollCheckError as exc:
        typer.echo(f"refusing — could not verify poll freshness: {exc}", err=True)
        raise typer.Exit(4) from exc


def _resolve_root_or_exit() -> Path:
    try:
        return repo_root()
    except UntrustedRootError as exc:
        typer.echo(f"refusing — {exc}", err=True)
        raise typer.Exit(4) from exc


def gate_resolve_and_promote(
    tranche: str, log: Path, snapshots_dir: Path, diff_dir: Path, manifest: Path,
    dry_run: bool, allow_behind: bool, reason: str | None,
) -> Path:
    """Poll-freshness + approval gate, snapshot resolution, and -- for a
    real (non-dry) run -- promotion. Returns the resolved snapshot."""
    enforce_poll_freshness(allow_behind, reason, tranche)
    snapshot = resolve_approved_snapshot(tranche, log, snapshots_dir, diff_dir)
    if not dry_run:
        promote_and_report(snapshot, manifest)
    return snapshot


def resolve_approved_snapshot(
    tranche: str, log: Path, snapshots_dir: Path, diff_dir: Path
) -> Path:
    """Gate + snapshot resolution for ``run``. Raises ``typer.Exit`` on failure."""
    if not is_tranche_approved(log, tranche):
        typer.echo(
            f"refusing to ingest — tranche {tranche[:12]} is not approved.\n"
            f"  Review the tranche-diff at {diff_dir}/tranche-diff-{tranche[:12]}.md\n"
            f"  then run `pursue ingest approve --tranche {tranche} --note ...`",
            err=True,
        )
        raise typer.Exit(1)
    snapshot = locate_snapshot(tranche, snapshots_dir)
    if snapshot is None:
        typer.echo(
            f"refusing to ingest — no snapshot found in {snapshots_dir} for {tranche[:12]}",
            err=True,
        )
        raise typer.Exit(2)
    return snapshot


def promote_and_report(snapshot: Path, manifest: Path) -> None:
    """Promote ``snapshot`` to every deploy-side surface and run the
    operator-local poster/thumb builders.

    The manifest mirror always lands -- a builder failure never rolls it
    back, and this prints the promotion confirmation before checking the
    builders. But a failed builder leaves a derived payload (an A/V
    poster, a PDF thumb) stale with no further signal downstream, so this
    now exits non-zero naming the builder instead of only warning.
    """
    failed = promote_snapshot(snapshot, manifest)
    typer.echo(f"promoted snapshot to {manifest}")
    if failed:
        names = ", ".join(failed)
        typer.echo(
            f"builder failure: {names} exited non-zero after promotion — "
            "the manifest mirror stands, but the derived payload is stale. "
            "See builder output above; re-run the builder directly once fixed.",
            err=True,
        )
        raise typer.Exit(1)
