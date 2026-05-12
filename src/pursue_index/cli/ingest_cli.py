"""Typer CLI for the ingest-approval gate.

Two subcommands:

  * `pursue ingest check --tranche <sha>` — exit 0 iff the tranche is
    approved; exit 1 otherwise. Used by downstream pipeline commands
    (and by the ingest orchestrator) to refuse to proceed against an
    unapproved tranche.

  * `pursue ingest approve --tranche <sha> --note "..."` — record an
    operator approval. Class A renames (byte-sha collisions in the
    tranche-diff report) are auto-included; Class C and other
    needs-judgment items are accepted via repeatable
    `--approve-rename <new_id>=<old_id>` flags.

This is thin glue over `pursue_index.ingest`. All logic lives there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from pursue_index.ingest import (
    append_aliases,
    auto_approve_renames,
    is_tranche_approved,
    parse_rename_flags,
    record_approval,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_APPROVAL_LOG = _REPO_ROOT / "data" / "tranche-approval-log.jsonl"
DEFAULT_ALIASES = _REPO_ROOT / "data" / "card-aliases.json"
DEFAULT_DIFF_DIR = _REPO_ROOT / ".paircoder" / "plans"


ingest_app = typer.Typer(
    name="ingest",
    help="Tranche-approval gate. Block deployed-corpus changes on unapproved tranches.",
)


def _find_diff_artifact(tranche_sha: str, diff_dir: Path) -> Path | None:
    """Locate the tranche-diff JSON for a given (full or prefix) sha.

    The diff artifacts use the first 12 chars of the sha. Accept either
    the full sha or the prefix as input.
    """
    prefix = tranche_sha[:12]
    candidate = diff_dir / f"tranche-diff-{prefix}.json"
    return candidate if candidate.exists() else None


@ingest_app.command("check")
def check_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256 (full or 12-char prefix)."),
    log: Path = typer.Option(DEFAULT_APPROVAL_LOG, "--log"),
) -> None:
    """Exit 0 if approved, 1 if not."""
    if is_tranche_approved(log, tranche):
        typer.echo(f"approved: {tranche}")
        raise typer.Exit(0)
    typer.echo(f"NOT approved: {tranche}", err=True)
    raise typer.Exit(1)


def _enrich_with_provenance(rows: list[dict], tranche_sha: str) -> list[dict]:
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    return [{**r, "established": now, "tranche_sha256": tranche_sha} for r in rows]


def _emit_approval_summary(
    tranche: str,
    auto_count: int,
    manual_count: int,
    diff_summary: dict,
) -> None:
    typer.echo(
        f"approved tranche {tranche[:12]}: "
        f"{auto_count} byte-collision renames + {manual_count} operator-manual renames"
    )
    quarantined = diff_summary.get("quarantined", 0)
    if quarantined > manual_count:
        unapproved = quarantined - manual_count
        typer.echo(
            f"note: {unapproved} quarantined card(s) not addressed; "
            f"gate clears but those renames are NOT in aliases.json. "
            f"Add --approve-rename <new>=<old> for each to materialize them.",
            err=True,
        )


def _load_diff_or_exit(tranche: str, diff_dir: Path) -> dict:
    diff_path = _find_diff_artifact(tranche, diff_dir)
    if diff_path is None:
        typer.echo(
            f"refusing to approve — no tranche-diff artifact found for {tranche} "
            f"in {diff_dir} (expected tranche-diff-{tranche[:12]}.json)",
            err=True,
        )
        raise typer.Exit(2)
    return json.loads(diff_path.read_text())


@ingest_app.command("approve")
def approve_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256."),
    note: str = typer.Option(..., "--note", help="Operator rationale; recorded in the audit log."),
    approve_rename: list[str] = typer.Option(
        None,
        "--approve-rename",
        help="Repeatable. Format: <new_card_id>=<old_card_id>. Each flag promotes a Class C quarantined card into an operator_manual alias.",
    ),
    log: Path = typer.Option(DEFAULT_APPROVAL_LOG, "--log"),
    aliases: Path = typer.Option(DEFAULT_ALIASES, "--aliases"),
    diff_dir: Path = typer.Option(DEFAULT_DIFF_DIR, "--diff-dir"),
) -> None:
    """Record an approval row + materialize the approved aliases."""
    diff = _load_diff_or_exit(tranche, diff_dir)
    diff_summary = diff.get("summary", {})
    auto_renames = auto_approve_renames(diff)
    try:
        manual_renames = parse_rename_flags(approve_rename or [])
    except ValueError as exc:
        typer.echo(f"refusing to approve — invalid --approve-rename: {exc}", err=True)
        raise typer.Exit(2)

    enriched = _enrich_with_provenance(auto_renames + manual_renames, tranche)
    record_approval(
        log_path=log,
        tranche_sha=tranche,
        note=note,
        diff_summary=diff_summary,
        renames_approved=enriched,
    )
    append_aliases(aliases, enriched)
    _emit_approval_summary(tranche, len(auto_renames), len(manual_renames), diff_summary)


def main() -> None:
    """Standalone entry point for `python -m pursue_index.cli.ingest_cli`."""
    ingest_app()


if __name__ == "__main__":
    main()
