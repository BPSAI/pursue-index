"""The pre-approval TOCTOU audit for ``pursue ingest approve``.

Re-fetches the bytes of every card the tranche-diff verdict depends on and
refuses the approval if any upstream sha changed between the diff and now.
Split out of ``ingest_cli`` to keep it under the arch limits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import typer

from pursue_index.post_ingest_audit import (
    audit_targets,
    collect_audit_targets,
    has_blocking_mismatch,
    render_audit_summary,
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
