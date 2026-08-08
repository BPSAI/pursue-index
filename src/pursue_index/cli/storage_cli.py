"""`pursue storage verify` — preflight the 3-tier storage-durability contract.

Thin glue over ``pursue_index.storage.contract`` (all logic + the same-account
finding live there). Exits non-zero if any tier (NAS / main R2 / backup R2) is
not configured, so the operator's ship path can gate on it before a release.
Credential-free: checks env-key presence only, never reads secret values.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from pursue_index.cli.worklist import read_worklist
from pursue_index.config import settings
from pursue_index.release.pdf_mirror import (
    render_mirror_report,
    render_preflight,
    run_pdf_mirror,
    select_pdf_cards,
    verify_pdf_mirror,
)
from pursue_index.scrape import load_manifest
from pursue_index.storage.contract import (
    render_contract_summary,
    verify_storage_contract,
)

_WORKLIST_OPT = typer.Option(
    ...,
    "--worklist",
    help="Path to the tranche worklist (card_ids, one per line; #-comments ok).",
)

storage_app = typer.Typer(
    name="storage",
    help="Archive storage-durability contract (NAS + main R2 + backup R2).",
)


@storage_app.command("verify")
def verify_cmd() -> None:
    """Verify all three storage tiers are configured; surface the DR risk.

    Exit 0 iff every tier resolves its configuring env keys. The same-account
    backup risk is printed as a WARNING but does not fail the check (it is a
    durability-posture finding needing an operator decision, not a
    misconfiguration).
    """
    result = verify_storage_contract(os.environ)
    typer.echo(render_contract_summary(result))
    raise typer.Exit(0 if result.ok else 1)


def _pdf_scope(worklist: Path) -> list[str]:
    """Worklist card_ids narrowed to PDF cards, echoing every exclusion.

    A tranche worklist covers the whole tranche — IMG/VID/AUD cards included.
    Those have no PDF, so gating them here fails them for lacking something
    they never had. Skips are printed, never silent: an unreported skip reads
    exactly like coverage.
    """
    card_ids = read_worklist(worklist)
    manifest = load_manifest(settings.manifests_dir / "latest.json")
    in_scope, skipped = select_pdf_cards(
        card_ids, [c.model_dump() for c in manifest.cards]
    )
    if skipped:
        by_type: dict[str, int] = {}
        for asset_type in skipped.values():
            by_type[asset_type] = by_type.get(asset_type, 0) + 1
        detail = ", ".join(f"{n}×{t}" for t, n in sorted(by_type.items()))
        typer.echo(
            f"[scope] {len(in_scope)}/{len(card_ids)} worklist cards are PDF; "
            f"skipped {len(skipped)} non-PDF ({detail}) — no PDF to mirror."
        )
    return in_scope


@storage_app.command("mirror-pdfs")
def mirror_pdfs_cmd(worklist: Path = _WORKLIST_OPT) -> None:
    """Content-address each in-scope card's PDF into ``r2-mirror/archive/``.

    Idempotent + sha-verified (already-mirrored cards are a no-op). Run AFTER
    OCR and BEFORE curate clean-qc. Exit non-zero if any card fails to mirror.
    """
    report = run_pdf_mirror(
        _pdf_scope(worklist),
        ocr_root=settings.ocr_dir,
        pdfs_root=settings.pdf_dir,
        mirror_root=settings.r2_mirror_dir,
    )
    typer.echo(render_mirror_report(report))
    raise typer.Exit(0 if report.ok else 1)


@storage_app.command("verify-mirror")
def verify_mirror_cmd(worklist: Path = _WORKLIST_OPT) -> None:
    """Fail-fast: every in-scope PDF card has its ``r2-mirror/archive/<sha>.pdf``.

    The gate the ship path runs immediately before clean-qc so a missing mirror
    errors loudly instead of producing silent ``missing_page_image`` verdicts.
    """
    pf = verify_pdf_mirror(
        _pdf_scope(worklist),
        ocr_root=settings.ocr_dir,
        mirror_root=settings.r2_mirror_dir,
    )
    typer.echo(render_preflight(pf))
    raise typer.Exit(0 if pf.ok else 1)


def main() -> None:
    storage_app()


if __name__ == "__main__":
    main()
