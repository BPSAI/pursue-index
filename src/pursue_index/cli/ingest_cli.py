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

import hashlib
import json
from pathlib import Path

import typer

from pursue_index.cli.ingest_from_diff import execute_from_diff
from pursue_index.ingest import (
    append_aliases,
    auto_approve_renames,
    is_tranche_approved,
    parse_rename_flags,
    record_approval,
)
from pursue_index.ingest_run import (
    locate_snapshot,
    promote_snapshot,
    render_next_steps,
    summarize_ingest_work,
)
from pursue_index.post_ingest_audit import (
    audit_targets,
    collect_audit_targets,
    has_blocking_mismatch,
    render_audit_summary,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_APPROVAL_LOG = _REPO_ROOT / "data" / "tranche-approval-log.jsonl"
DEFAULT_ALIASES = _REPO_ROOT / "data" / "card-aliases.json"
# Must match scripts/tranche_diff.py::DEFAULT_OUT_DIR, and must be tracked —
# `.paircoder/` is gitignored, so receipts written there never get committed.
DEFAULT_DIFF_DIR = _REPO_ROOT / "data" / "tranche-diffs"
DEFAULT_MANIFEST_SNAPSHOTS = _REPO_ROOT / "data" / "manifests" / "snapshots"
DEFAULT_LATEST_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_WORKLIST = _REPO_ROOT / "data" / "ingest-worklist.txt"

_OPT_APPROVE_RENAME = typer.Option(
    None,
    "--approve-rename",
    help="Repeatable. Format: <new_card_id>=<old_card_id>. Each flag promotes a Class C "
    "quarantined card into an operator_manual alias.",
)
_OPT_SKIP_AUDIT = typer.Option(
    False,
    "--skip-audit",
    help="Skip the TOCTOU re-fetch audit. NOT RECOMMENDED — use only with explicit reason.",
)
_OPT_FROM_DIFF_COST_CAP = typer.Option(
    None,
    "--cost-cap-usd",
    help="With --from-diff: override the embed stage cost cap (USD) so a large "
    "tranche isn't blocked at the default cap. Omit to use the embed default.",
)
_OPT_FROM_DIFF = typer.Option(
    False,
    "--from-diff",
    help="One-command path: export the scoped work-list from the tranche-diff "
    "and run the scoped download -> ocr -> embed stages (T6.5 --worklist).",
)
_OPT_DRY_RUN = typer.Option(
    False,
    "--dry-run",
    help="With --from-diff: print the work-list (the card_ids that would be "
    "OCR'd/embedded) WITHOUT running any stage or spending budget.",
)
_OPT_WORKLIST_OUT = typer.Option(
    DEFAULT_WORKLIST,
    "--worklist",
    help="Where --from-diff writes the scoped card_id list the executors read.",
)


def _fetch_byte_sha_via_curl(url: str) -> str | None:
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=300)
        resp.raise_for_status()
        return hashlib.sha256(resp.content).hexdigest()
    except Exception as exc:
        typer.echo(f"[audit] fetch fail {url}: {exc}", err=True)
        return None


def _load_new_manifest(tranche_sha: str, snapshots_dir: Path) -> dict | None:
    """Find the snapshot manifest for the given tranche sha."""
    for path in snapshots_dir.glob(f"{tranche_sha}*.json"):
        return json.loads(path.read_text())
    return None


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


def _run_pre_approval_audit(
    enriched_aliases: list[dict],
    diff: dict,
    tranche: str,
    snapshots_dir: Path,
    skip_audit: bool,
) -> list[dict]:
    """Run the TOCTOU re-verification audit. Returns audit results.
    Raises typer.Exit(3) on blocking mismatch."""
    if skip_audit:
        typer.echo("[audit] --skip-audit set; TOCTOU re-verification skipped", err=True)
        return []
    new_manifest = _load_new_manifest(tranche, snapshots_dir)
    if new_manifest is None:
        typer.echo(
            f"[audit] WARNING: no snapshot manifest found at {snapshots_dir} for "
            f"tranche {tranche[:12]} — skipping audit (operator_manual-only approval?)",
            err=True,
        )
        return []
    targets = collect_audit_targets(enriched_aliases, diff, new_manifest)
    results = audit_targets(targets, _fetch_byte_sha_via_curl)
    typer.echo(render_audit_summary(results), err=True)
    if has_blocking_mismatch(results):
        typer.echo(
            "refusing to approve — audit detected upstream sha mismatch. "
            "Bytes changed between tranche-diff and approval. "
            "Review the mismatched cards before re-attempting "
            "(or use --skip-audit if you have an explicit reason).",
            err=True,
        )
        raise typer.Exit(3)
    return results


@ingest_app.command("approve")
def approve_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256."),
    note: str = typer.Option(..., "--note", help="Operator rationale; recorded in the audit log."),
    approve_rename: list[str] = _OPT_APPROVE_RENAME,
    log: Path = typer.Option(DEFAULT_APPROVAL_LOG, "--log"),
    aliases: Path = typer.Option(DEFAULT_ALIASES, "--aliases"),
    diff_dir: Path = typer.Option(DEFAULT_DIFF_DIR, "--diff-dir"),
    snapshots_dir: Path = typer.Option(DEFAULT_MANIFEST_SNAPSHOTS, "--snapshots-dir"),
    skip_audit: bool = _OPT_SKIP_AUDIT,
) -> None:
    """Record an approval row + materialize the approved aliases.

    Runs a pre-approval audit (re-fetches upstream bytes for byte-collision
    renames and restored_unchanged events) to catch TOCTOU swaps between
    tranche-diff and approval. Refuses approval if any sha mismatches.
    """
    diff = _load_diff_or_exit(tranche, diff_dir)
    diff_summary = diff.get("summary", {})
    auto_renames = auto_approve_renames(diff)
    try:
        manual_renames = parse_rename_flags(approve_rename or [])
    except ValueError as exc:
        typer.echo(f"refusing to approve — invalid --approve-rename: {exc}", err=True)
        raise typer.Exit(2) from exc

    enriched = _enrich_with_provenance(auto_renames + manual_renames, tranche)
    audit_results = _run_pre_approval_audit(
        enriched, diff, tranche, snapshots_dir, skip_audit
    )
    record_approval(
        log_path=log,
        tranche_sha=tranche,
        note=note,
        diff_summary=diff_summary,
        renames_approved=enriched,
    )
    if audit_results:
        # Audit results are part of the audit trail.
        log_dir = log.parent
        audit_log = log_dir / "audit-log.jsonl"
        with audit_log.open("a") as fh:
            fh.write(json.dumps({
                "tranche_sha256": tranche,
                "results": audit_results,
            }) + "\n")
    append_aliases(aliases, enriched)
    _emit_approval_summary(tranche, len(auto_renames), len(manual_renames), diff_summary)


def _resolve_approved_snapshot(
    tranche: str, log: Path, snapshots_dir: Path, diff_dir: Path
) -> Path:
    """Gate + snapshot resolution for ``run``. Raises typer.Exit on failure."""
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


@ingest_app.command("run")
def run_cmd(
    tranche: str = typer.Option(..., "--tranche", help="Tranche csv_sha256."),
    log: Path = typer.Option(DEFAULT_APPROVAL_LOG, "--log"),
    snapshots_dir: Path = typer.Option(DEFAULT_MANIFEST_SNAPSHOTS, "--snapshots-dir"),
    manifest: Path = typer.Option(DEFAULT_LATEST_MANIFEST, "--manifest"),
    diff_dir: Path = typer.Option(DEFAULT_DIFF_DIR, "--diff-dir"),
    from_diff: bool = _OPT_FROM_DIFF,
    dry_run: bool = _OPT_DRY_RUN,
    worklist: Path = _OPT_WORKLIST_OUT,
    cost_cap_usd: float = _OPT_FROM_DIFF_COST_CAP,
    engine: str = typer.Option(
        None, "--engine", help="With --from-diff: OCR engine passthrough (operated: llm-dots)."
    ),
    force: bool = typer.Option(
        False, "--force", help="With --from-diff: force re-OCR (overwrite status=ok)."
    ),
    concurrency: int = typer.Option(
        None, "--concurrency", help="With --from-diff: OCR concurrency passthrough (operated: 8)."
    ),
) -> None:
    """Promote an approved tranche to the deployed manifest + report next steps.

    Refuses if the tranche is not approved. Promotes the snapshot to
    data/manifests/latest.json. Identifies downstream pipeline work
    (download/ocr/embed) required by any new content in the tranche.

    By default it prints copy-paste-ready next-step commands. With
    ``--from-diff`` it instead exports the scoped work-list and drives the
    scoped stages itself; ``--dry-run`` shows the work-list without spending.
    """
    snapshot = _resolve_approved_snapshot(tranche, log, snapshots_dir, diff_dir)
    diff_payload = _load_diff_or_exit(tranche, diff_dir)
    summary = summarize_ingest_work(diff_payload)
    promote_snapshot(snapshot, manifest)
    typer.echo(f"promoted snapshot to {manifest}")
    if from_diff:
        execute_from_diff(
            summary,
            tranche=tranche,
            manifest=manifest,
            worklist=worklist,
            dry_run=dry_run,
            engine=engine,
            force=force,
            concurrency=concurrency,
            cost_cap_usd=cost_cap_usd,
        )
        return
    typer.echo("")
    typer.echo(render_next_steps(summary))


def main() -> None:
    """Standalone entry point for `python -m pursue_index.cli.ingest_cli`."""
    ingest_app()


if __name__ == "__main__":
    main()
