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
from pathlib import Path

import typer

from pursue_index import ingest as ing
from pursue_index.cli import ingest_options as opt
from pursue_index.cli.ingest_audit import _run_pre_approval_audit, check_tranche

# Re-exports the DEFAULT_* data paths (resolved on access) for importers.
from pursue_index.cli.ingest_defaults import __getattr__  # noqa: F401
from pursue_index.cli.ingest_estimate import ingest_estimate_record, ingest_estimate_text
from pursue_index.cli.ingest_from_diff import execute_from_diff
from pursue_index.cli.ingest_promote import enforce_poll_freshness, gate_resolve_and_promote
from pursue_index.config import settings
from pursue_index.ingest_run import render_next_steps, summarize_ingest_work
from pursue_index.tranche_resave import RESAVE_METHOD

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
    log: Path = opt._OPT_RUN_LOG,
) -> None:
    """Exit 0 if approved, 1 if not."""
    if ing.is_tranche_approved(log, tranche):
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
    auto_renames: list[dict],
    manual_count: int,
    diff_summary: dict,
    estimate_text: str = "",
) -> None:
    resaves = sum(r["method"] == RESAVE_METHOD for r in auto_renames)
    typer.echo(
        f"approved tranche {tranche[:12]}: {len(auto_renames) - resaves} byte-collision "
        f"renames + {resaves} metadata-only re-save renames + {manual_count} "
        "operator-manual renames"
    )
    if estimate_text:
        typer.echo(estimate_text)
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


def _load_diff_and_summarize(tranche: str, diff_dir: Path) -> tuple[dict, dict]:
    """Shared prefix of every ``run`` path: load the diff, summarize the work."""
    diff_payload = _load_diff_or_exit(tranche, diff_dir)
    return diff_payload, summarize_ingest_work(diff_payload)


def _echo_estimate(diff_payload: dict, summary: dict) -> None:
    """Print the per-page cost estimate when the tranche has OCR work."""
    if estimate := ingest_estimate_text(diff_payload, summary):
        typer.echo("\n" + estimate)


def _resolve_renames(
    diff: dict, tranche: str, approve_rename: list[str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Auto (Class A + metadata-only re-save) and Class C (manual) renames,
    enriched with provenance.
    Returns ``(auto_renames, manual_renames, enriched)``. Exits 2 on a
    malformed ``--approve-rename`` flag."""
    opted_in = settings.ingest_auto_approve_metadata_resaves
    if refusal := ing.resave_setting_mismatch(diff, opted_in, approve_rename or []):
        typer.echo(refusal, err=True)
        raise typer.Exit(2)
    auto_renames = ing.auto_approve_renames(diff, metadata_resaves=opted_in)
    for line in ing.held_resave_lines(diff, enabled=opted_in):
        typer.echo(line, err=True)
    try:
        manual_renames = ing.parse_rename_flags(approve_rename or [])
    except ValueError as exc:
        typer.echo(f"refusing to approve — invalid --approve-rename: {exc}", err=True)
        raise typer.Exit(2) from exc
    manual_renames = ing.attach_resave_evidence(manual_renames, diff)
    enriched = _enrich_with_provenance(auto_renames + manual_renames, tranche)
    return auto_renames, manual_renames, enriched


def _persist_approval(
    tranche: str, note: str, log: Path, aliases: Path,
    diff_summary: dict, enriched: list[dict], audit_results: list,
    cost_estimate: dict | None = None, audit: str | None = None,
) -> None:
    """Write the approval row, fold in the audit trail, materialize aliases."""
    ing.record_approval(
        log_path=log, tranche_sha=tranche, note=note, diff_summary=diff_summary,
        renames_approved=enriched, cost_estimate=cost_estimate,
        audit=audit,
    )
    if audit_results:
        audit_log = log.parent / "audit-log.jsonl"
        with audit_log.open("a") as fh:
            fh.write(json.dumps({"tranche_sha256": tranche, "results": audit_results}) + "\n")
    ing.append_aliases(aliases, enriched)


@ingest_app.command("approve")
def approve_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256."),
    note: str = typer.Option(..., "--note", help="Operator rationale; recorded in the audit log."),
    approve_rename: list[str] = opt._OPT_APPROVE_RENAME,
    log: Path = opt._OPT_APPROVE_LOG,
    aliases: Path = opt._OPT_APPROVE_ALIASES,
    diff_dir: Path = opt._OPT_APPROVE_DIFF_DIR,
    snapshots_dir: Path = opt._OPT_APPROVE_SNAPSHOTS_DIR,
    skip_audit: bool = opt._OPT_SKIP_AUDIT,
    allow_behind: bool = opt._OPT_ALLOW_BEHIND,
    reason: str = opt._OPT_BEHIND_REASON,
) -> None:
    """Record an approval row + materialize the approved aliases.

    Refuses if this checkout is behind origin/main on the paths the
    poller writes (see `pursue_index.poll_freshness`); runs a pre-approval
    audit (re-fetches upstream bytes for byte-collision renames and
    restored_unchanged events) to catch TOCTOU swaps between tranche-diff
    and approval. Refuses approval if any sha mismatches.
    """
    check_tranche(tranche)
    enforce_poll_freshness(allow_behind, reason, tranche)
    diff = _load_diff_or_exit(tranche, diff_dir)
    diff_summary = diff.get("summary", {})
    auto_renames, manual_renames, enriched = _resolve_renames(diff, tranche, approve_rename)
    audit_results, audit_label = _run_pre_approval_audit(
        enriched, diff, tranche, snapshots_dir, skip_audit, reason)
    work = summarize_ingest_work(diff)
    _persist_approval(tranche, note, log, aliases, diff_summary, enriched, audit_results,
                      ingest_estimate_record(diff, work), audit_label)
    _emit_approval_summary(tranche, auto_renames, len(manual_renames), diff_summary,
                           ingest_estimate_text(diff, work))


@ingest_app.command("run")
def run_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256."),
    log: Path = opt._OPT_RUN_LOG,
    snapshots_dir: Path = opt._OPT_RUN_SNAPSHOTS_DIR,
    manifest: Path = opt._OPT_RUN_MANIFEST,
    diff_dir: Path = opt._OPT_RUN_DIFF_DIR,
    aliases: Path = opt._OPT_RUN_ALIASES,
    asset_registry: Path = opt._OPT_RUN_ASSET_REGISTRY,
    from_diff: bool = opt._OPT_FROM_DIFF,
    dry_run: bool = opt._OPT_DRY_RUN,
    worklist: Path = opt._OPT_WORKLIST_OUT,
    cost_cap_usd: float = opt._OPT_FROM_DIFF_COST_CAP,
    engine: str = opt._OPT_RUN_ENGINE,
    force: bool = opt._OPT_RUN_FORCE,
    concurrency: int = opt._OPT_RUN_CONCURRENCY,
    allow_behind: bool = opt._OPT_ALLOW_BEHIND,
    reason: str = opt._OPT_BEHIND_REASON,
) -> None:
    """Promote an approved tranche to the deployed manifest + report next steps.

    Refuses if this checkout is behind origin/main on the paths the
    poller writes (see `pursue_index.poll_freshness`), or if the tranche
    is not approved. With ``--dry-run`` nothing is
    promoted and no builder runs — only the work-list(s) are written (or,
    without ``--from-diff``, just the scope is printed), so an operator can
    inspect scope before anything is spent or mirrored. Without
    ``--dry-run``, promotes the snapshot to data/manifests/latest.json (and
    its deploy-side mirrors), runs the poster/thumb builders, then
    identifies downstream pipeline work (download/ocr/embed) required by
    any new content in the tranche.

    By default it prints copy-paste-ready next-step commands. With
    ``--from-diff`` it instead exports the scoped work-list and drives the
    scoped stages itself; ``--dry-run`` shows the work-list without spending
    or promoting.
    """
    gate_resolve_and_promote(tranche, log, snapshots_dir, diff_dir, manifest, dry_run, allow_behind, reason)
    diff_payload, summary = _load_diff_and_summarize(tranche, diff_dir)
    if not from_diff:  # --from-diff prices the exact scoped list it is about to run
        _echo_estimate(diff_payload, summary)
    if from_diff:
        execute_from_diff(
            summary, diff=diff_payload, tranche=tranche, manifest=manifest, worklist=worklist,
            dry_run=dry_run, aliases_path=aliases, registry_path=asset_registry,
            ocr_dir=settings.ocr_dir, engine=engine, force=force,
            concurrency=concurrency, cost_cap_usd=cost_cap_usd,
        )
        return
    typer.echo("\n" + render_next_steps(summary))


def main() -> None:
    """Standalone entry point for `python -m pursue_index.cli.ingest_cli`."""
    ingest_app()


if __name__ == "__main__":
    main()
