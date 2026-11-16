"""The pre-approval TOCTOU audit for ``pursue ingest approve``.

Re-fetches the bytes of every card the tranche-diff verdict depends on and
refuses the approval if any upstream sha changed between the diff and now.
Split out of ``ingest_cli`` to keep it under the arch limits.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import typer

from pursue_index.poll_freshness import require_reason
from pursue_index.post_ingest_audit import (
    audit_targets,
    collect_audit_targets,
    has_blocking_mismatch,
    render_audit_summary,
)

# A tranche is a csv sha256; operators may pass a 12+ character prefix. Checked
# before it goes into a glob pattern.
_TRANCHE = re.compile(r"[0-9a-f]{12,64}")


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


def _refuse(why: str) -> None:
    typer.echo(f"refusing to approve — {why}. Pass --skip-audit --reason <why> to approve "
               "without the audit; the reason is recorded on the approval row.", err=True)
    raise typer.Exit(3)


def _skip_reason(reason: str | None) -> str:
    """The recorded reason for --skip-audit; too thin a reason is a usage error."""
    try:
        return require_reason(reason)
    except ValueError as exc:
        typer.echo(f"--skip-audit needs --reason: {exc}", err=True)
        raise typer.Exit(2) from exc


def _run_pre_approval_audit(
    enriched_aliases: list[dict],
    diff: dict,
    tranche: str,
    snapshots_dir: Path,
    skip_audit: bool,
    reason: str | None = None,
) -> tuple[list[dict], str | None]:
    """Run the TOCTOU re-verification audit; return ``(results, skip_reason)``.

    Fails closed: refuses (exit 3) on a blocking mismatch, and also when the
    audit could verify nothing -- no snapshot manifest, ``curl_cffi`` not
    installed, or every fetchable target ``fetch_failed``. ``--skip-audit``
    bypasses it only with a ``--reason``, which the caller records. A tranche
    with no byte-changing targets has nothing to verify and passes.
    """
    if not _TRANCHE.fullmatch(tranche):
        typer.echo(f"--tranche must be 12-64 lowercase hex characters, got {tranche!r}", err=True)
        raise typer.Exit(2)
    if skip_audit:
        why = _skip_reason(reason)
        typer.echo(f"[audit] --skip-audit set; TOCTOU re-verification skipped: {why}", err=True)
        return [], why
    new_manifest = _load_new_manifest(tranche, snapshots_dir)
    if new_manifest is None:
        _refuse(f"no snapshot manifest at {snapshots_dir} for tranche {tranche[:12]}, "
                "so the audit cannot verify anything")
    targets = collect_audit_targets(enriched_aliases, diff, new_manifest)
    if targets and importlib.util.find_spec("curl_cffi") is None:
        _refuse("the audit needs curl_cffi to re-fetch upstream bytes and it is not installed")
    results = audit_targets(targets, _fetch_byte_sha_via_curl)
    typer.echo(render_audit_summary(results), err=True)
    if has_blocking_mismatch(results):
        typer.echo(
            "refusing to approve — audit detected upstream sha mismatch. "
            "Bytes changed between tranche-diff and approval. "
            "Review the mismatched cards before re-attempting "
            "(or use --skip-audit --reason <why> if you have an explicit reason).",
            err=True,
        )
        raise typer.Exit(3)
    fetchable = [r for r in results if r.get("status") != "skipped"]
    if fetchable and all(r.get("status") == "fetch_failed" for r in fetchable):
        _refuse(f"every one of the {len(fetchable)} audit fetch(es) failed, so nothing was verified")
    return results, None
