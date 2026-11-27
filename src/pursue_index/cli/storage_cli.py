"""`pursue storage verify` — preflight the 3-tier storage-durability contract.

Thin glue over ``pursue_index.storage.contract`` (all logic + the same-account
finding live there). Exits non-zero if any tier (NAS / main R2 / backup R2) is
not configured, so the operator's ship path can gate on it before a release.
Credential-free: checks env-key presence only, never reads secret values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from pursue_index.card_id import InvalidCardIdError, require_card_ids
from pursue_index.cli.worklist import (
    WorklistTrancheError,
    exit_on_tranche_error,
    read_worklist,
    require_worklist_tranche,
)
from pursue_index.config import settings
from pursue_index.release.image_mirror import (
    UnresolvedCard,
    render_image_mirror_report,
    render_image_verify,
    run_image_mirror,
    select_image_cards,
    verify_image_mirror,
)
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
from pursue_index.storage.data_root import (
    DataRootProbe,
    ocr_coverage,
    probe_data_root,
    render_data_root_lines,
)
from pursue_index.vision.img_source import default_registry_path

_WORKLIST_OPT = typer.Option(
    ...,
    "--worklist",
    help="Path to the tranche worklist (card_ids, one per line; #-comments ok).",
)

_ALL_IMAGES_OPT = typer.Option(
    False,
    "--all-image-cards",
    help="Every IMG card in the manifest, no tranche gate; for the "
    "operator-attended backfill. Exclusive with --worklist.",
)
_OPT_WORKLIST = typer.Option(None, "--worklist", help=_WORKLIST_OPT.help)

storage_app = typer.Typer(
    name="storage",
    help="Archive storage-durability contract (NAS + main R2 + backup R2).",
)


@storage_app.command("verify")
def verify_cmd() -> None:
    """Verify all three storage tiers are configured; surface the DR risk.

    Exit 0 iff every tier resolves its configuring env keys AND the data root
    is reachable (a ``stat`` of ``PURSUE_DATA_ROOT`` — configured is not the
    same as mounted). The same-account backup risk is printed as a WARNING but
    does not fail the check (it is a durability-posture finding needing an
    operator decision, not a misconfiguration). OCR coverage
    (``<manifest cards with pages.jsonl>/<manifest cards>``) is reported for a
    mounted root so a thin root is visible before a derivative rebuild.
    """
    result = verify_storage_contract(os.environ)
    probe = probe_data_root(os.environ)
    typer.echo(render_contract_summary(result))
    typer.echo("")
    for line in render_data_root_lines(probe, _coverage(probe)):
        typer.echo(line)
    unreachable = probe.configured and not probe.mounted
    if unreachable:
        typer.echo(f"ERROR: data root {probe.root} is configured but not reachable.")
    raise typer.Exit(0 if result.ok and not unreachable else 1)


def _coverage(probe: DataRootProbe) -> tuple[int, int] | None:
    """OCR coverage of the mounted root, or ``None`` if it cannot be measured."""
    manifest_path = settings.manifests_dir / "latest.json"
    if probe.root is None or not probe.mounted or not manifest_path.exists():
        return None
    # Raw JSON, like the derivative builders: a preflight must not fail on a
    # manifest-schema field it never reads.
    cards = json.loads(manifest_path.read_text(encoding="utf-8"))["cards"]
    return ocr_coverage(probe.root / "ocr", cards)


def _worklist_card_ids(worklist: Path, manifest) -> list[str]:
    """Tranche-gated, validated card_ids of ``worklist`` (exits on refusal)."""
    try:
        require_worklist_tranche(worklist, manifest.csv_sha256)
    except WorklistTrancheError as exc:
        exit_on_tranche_error(exc)
    try:
        return require_card_ids(read_worklist(worklist))
    except InvalidCardIdError as exc:
        typer.echo(f"refusing — worklist {worklist}: {exc}", err=True)
        raise typer.Exit(2) from exc


def _pdf_scope(worklist: Path) -> list[str]:
    """Worklist card_ids narrowed to PDF cards, echoing every exclusion.

    A tranche worklist covers the whole tranche — IMG/VID/AUD cards included.
    Those have no PDF, so gating them here fails them for lacking something
    they never had. Skips are printed, never silent: an unreported skip reads
    exactly like coverage.
    """
    manifest = load_manifest(settings.manifests_dir / "latest.json")
    card_ids = _worklist_card_ids(worklist, manifest)
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


def _image_cards(worklist: Path | None, all_image_cards: bool) -> list:
    """The IMG manifest cards in scope (worklist-narrowed, or every IMG card)."""
    if all_image_cards == (worklist is not None):
        typer.echo("refusing — give exactly one of --worklist / --all-image-cards", err=True)
        raise typer.Exit(2)
    manifest = load_manifest(settings.manifests_dir / "latest.json")
    img_cards = [c for c in manifest.cards if c.asset_type == "IMG"]
    if all_image_cards:
        typer.echo(
            f"[scope] --all-image-cards: {len(img_cards)} IMG cards from the manifest "
            "(no tranche gate)"
        )
        return img_cards
    assert worklist is not None
    card_ids = _worklist_card_ids(worklist, manifest)
    in_scope, skipped = select_image_cards(
        card_ids, [c.model_dump() for c in manifest.cards]
    )
    if skipped:
        typer.echo(
            f"[scope] {len(in_scope)}/{len(card_ids)} worklist cards are IMG; "
            f"skipped {len(skipped)} non-IMG — no image to mirror."
        )
    wanted = set(in_scope)
    known = {c.card_id for c in manifest.cards}
    cards: list = [c for c in img_cards if c.card_id in wanted]
    # An id the manifest cannot resolve stays gated (verify and mirror fail).
    cards += [UnresolvedCard(cid) for cid in in_scope if cid not in known]
    return cards


@storage_app.command("mirror-images")
def mirror_images_cmd(
    worklist: Path | None = _OPT_WORKLIST, all_image_cards: bool = _ALL_IMAGES_OPT
) -> None:
    """Content-address each IMG card's images/ file into ``r2-mirror/archive/``.

    Idempotent + sha-verified against the registry's newest byte_sha256; never
    overwrites. Exit non-zero if any card fails. The first run after this stage
    landed should use --all-image-cards (operator-attended backfill).
    """
    report = run_image_mirror(
        _image_cards(worklist, all_image_cards),
        images_root=settings.image_dir,
        mirror_root=settings.r2_mirror_dir,
        registry_path=default_registry_path(),
    )
    typer.echo(render_image_mirror_report(report))
    raise typer.Exit(0 if report.ok else 1)


@storage_app.command("verify-image-mirror")
def verify_image_mirror_cmd(
    worklist: Path | None = _OPT_WORKLIST, all_image_cards: bool = _ALL_IMAGES_OPT
) -> None:
    """Fail-fast: every in-scope IMG card has its sha-matching archive copy."""
    pf = verify_image_mirror(
        _image_cards(worklist, all_image_cards),
        mirror_root=settings.r2_mirror_dir,
        registry_path=default_registry_path(),
    )
    typer.echo(render_image_verify(pf))
    raise typer.Exit(0 if pf.ok else 1)


def main() -> None:
    storage_app()


if __name__ == "__main__":
    main()
