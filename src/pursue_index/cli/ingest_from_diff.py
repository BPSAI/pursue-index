"""``pursue ingest run --from-diff`` work-list export + scoped-stage driver.

The operator's one-command path after a ``needs-review`` tranche clears the
gate: turn the tranche-diff into the scoped card-set, show it (``--dry-run``)
or run it (download -> ocr -> embed via the ``--worklist`` path).

PDF/IMG work-list contents: ``pursue_index.ingest_scope.scope_worklist`` --
every card_id this tranche must (re)download/OCR/embed: Class B
(``new``), approved-and-unaddressed Class C (``quarantined-new``), the new
side of this tranche's approved renames (``renamed``), and any existing card
whose registry byte sha has drifted from its OCR sidecar's (``bytes-changed``).
See R7C.1 / #168 -- ``summarize_ingest_work`` alone only ever covered the
first of those four. The work-list is ALWAYS (re)written, even when empty,
so a prior tranche's scope can never survive into this one.

A/V work-list contents (unchanged): ``summarize_ingest_work``'s
``needs_av_fetch``, first-seen order kept.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from pursue_index.card_id import require_card_ids
from pursue_index.cli.ingest_estimate import ingest_estimate_text
from pursue_index.cli.worklist import WorklistTrancheError, exit_on_tranche_error
from pursue_index.config.credentials import anthropic_api_key
from pursue_index.ingest_run import render_av_next_steps
from pursue_index.ingest_scope import ScopedCard, scope_worklist


def scoped_av_card_ids(summary: dict[str, Any]) -> list[str]:
    """Extract needs_av_fetch card_ids (VID/AUD rows), first-seen order kept."""
    return list(summary.get("needs_av_fetch", []) or [])


def write_worklist_file(path: Path, card_ids: list[str], tranche: str, suffix: str = "") -> None:
    """Write the A/V work-list: scoped card_ids to ``path``, one per line, with
    a header. If suffix is provided (e.g. "-av"), it's inserted between the
    file's stem and its extension.
    """
    if suffix:
        path = path.with_name(path.stem + suffix + path.suffix)
    card_ids = require_card_ids(card_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# worklist for tranche {tranche[:12]} (pursue ingest run --from-diff)",
        f"# {len(card_ids)} card_id(s) scoped from the tranche-diff",
        *card_ids,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_scoped_worklist(path: Path, scoped: list[ScopedCard], tranche_sha: str) -> None:
    """Write the PDF/IMG work-list: one ``# tranche: <sha>`` header every
    consumer validates against the promoted manifest, then one
    ``card_id<TAB>reason`` row per scoped card (``new`` / ``quarantined-new``
    / ``renamed`` / ``bytes-changed``). Written even when ``scoped`` is
    empty, so a prior tranche's ids can never survive into this one.
    """
    require_card_ids(c.card_id for c in scoped)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# tranche: {tranche_sha}",
        f"# {len(scoped)} card_id(s) scoped from the tranche-diff "
        "(reason: new | quarantined-new | renamed | bytes-changed)",
        *(f"{c.card_id}\t{c.reason}" for c in scoped),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_scoped_stages(
    manifest: Path,
    worklist: Path,
    *,
    engine: str | None = None,
    force: bool = False,
    concurrency: int | None = None,
    cost_cap_usd: float | None = None,
) -> None:
    """Drive download -> ocr -> embed scoped to ``worklist``.

    Calls the executor functions directly (rather than shelling out) so the
    real ``--worklist`` subsetting runs and the deep stage functions remain
    monkeypatch-able in tests. The non-cost-cap embed defaults are sourced from
    ``embed_cli``'s own ``typer.Option`` defaults (single source of truth — they
    can't silently diverge from a manual ``pursue embed run``). ``cost_cap_usd``
    is the operator escape hatch for a large tranche; ``None`` uses the embed
    default. ``engine``/``force``/``concurrency`` pass through to the OCR stage so
    the one-command path can run the operated forced all-Sonnet config
    (``--engine llm-dots --force --concurrency 8``); defaults keep the prior
    contract.
    """
    from pursue_index.cli import embed_cli
    from pursue_index.cli.download_ocr_cli import download_run, ocr_run

    cap = cost_cap_usd if cost_cap_usd is not None else embed_cli._OPT_COST_CAP.default
    download_run(manifest=manifest, worklist=worklist)
    ocr_run(
        manifest=manifest,
        engine=engine,
        force=force,
        concurrency=concurrency,
        worklist=worklist,
    )
    embed_cli.embed_run_cmd(
        manifest=manifest,
        provider=None,
        model=None,
        limit=None,
        cost_cap_usd=cap,
        usd_per_million_tokens=None,
        batch_size=embed_cli._OPT_BATCH.default,
        image_observations_index=embed_cli._OPT_IMAGE_OBS_INDEX.default,
        worklist=worklist,
    )


def _enforce_ocr_preflight(engine: str | None, concurrency: int | None) -> None:
    """Verify-before-spend gate for the ``--from-diff`` spend path.

    The scoped OCR stage below is a real spend. Before it runs we consult the
    same ``preflight_ocr`` guard the ``/ship-tranche`` command uses, resolving
    ``engine``/``concurrency`` from the operated env vars when the flags are
    omitted. This closes the gap where a direct ``pursue ingest run --from-diff``
    (or a stale ``PURSUE_OCR_ENGINE=auto`` env) could spend on the retired
    tesseract path with no refusal. Raises ``typer.Exit(1)`` on any violation.
    """
    from pursue_index.release.ship import preflight_ocr

    eng = engine or os.environ.get("PURSUE_OCR_ENGINE")
    conc = concurrency
    if conc is None:
        raw = os.environ.get("PURSUE_OCR_LLM_CONCURRENCY")
        conc = int(raw) if raw and raw.isdigit() else None
    result = preflight_ocr(
        engine=eng,
        concurrency=conc,
        anthropic_key_present=bool(anthropic_api_key()),
    )
    if not result.ok:
        for err in result.errors:
            typer.echo(f"[preflight] {err}", err=True)
        typer.echo(
            "refusing to spend on OCR — the operated methodology is not satisfied "
            "(pass --engine llm-dots --concurrency 8, or fix the env). See above.",
            err=True,
        )
        raise typer.Exit(1)


def _print_worklists(
    scoped: list[ScopedCard], av_card_ids: list[str]
) -> bool:
    """Print PDF and A/V worklists. Return False if metadata-only (no work)."""
    typer.echo("")
    typer.echo(f"work-list ({len(scoped)} card_id(s) to download/ocr/embed):")
    for c in scoped:
        typer.echo(f"  {c.card_id}\t{c.reason}")
    if not scoped:
        typer.echo("  (none -- no PDF/IMG cards scoped for this tranche)")

    if av_card_ids:
        typer.echo("")
        typer.echo(f"A/V work-list ({len(av_card_ids)} card_id(s) for av-fetch/transcribe):")
        for cid in av_card_ids:
            typer.echo(f"  {cid}")

    if not scoped and not av_card_ids:
        typer.echo("  (none -- metadata-only tranche; no scoped stages to run)")
        return False
    return True


def _write_worklists(
    scoped: list[ScopedCard], av_card_ids: list[str], worklist: Path, tranche_sha: str
) -> None:
    """Write both PDF and A/V worklist files.

    The PDF list is written even when empty, so a list left by an earlier
    tranche can never be read as this one's scope.
    """
    write_scoped_worklist(worklist, scoped, tranche_sha)
    if av_card_ids:
        write_worklist_file(worklist, av_card_ids, tranche_sha, suffix="-av")


def _write_and_run(
    scoped: list[ScopedCard],
    av_card_ids: list[str],
    *,
    manifest: Path,
    worklist: Path,
    tranche_sha: str,
    dry_run: bool,
    engine: str | None,
    force: bool,
    concurrency: int | None,
    cost_cap_usd: float | None,
) -> None:
    """The three ways ``execute_from_diff`` can end: dry-run (write only),
    metadata-only (write only, nothing to spend on), or a real spend (write,
    preflight, then run the scoped stages)."""
    if dry_run:
        _write_worklists(scoped, av_card_ids, worklist, tranche_sha)
        typer.echo("")
        typer.echo(
            f"--dry-run: wrote work-list(s) -> {worklist.parent} (no spend, no "
            "promotion); stages NOT executed. Re-run without --dry-run to ingest."
        )
        return
    if not scoped:
        _write_worklists(scoped, av_card_ids, worklist, tranche_sha)
        typer.echo("")
        typer.echo("0 PDF/IMG cards — PDF stages skipped")
        return
    _enforce_ocr_preflight(engine, concurrency)
    _write_worklists(scoped, av_card_ids, worklist, tranche_sha)
    typer.echo("")
    typer.echo("wrote work-list(s); running scoped download -> ocr -> embed")
    try:
        run_scoped_stages(
            manifest, worklist,
            engine=engine, force=force, concurrency=concurrency, cost_cap_usd=cost_cap_usd,
        )
    except WorklistTrancheError as exc:
        exit_on_tranche_error(exc)


def execute_from_diff(
    summary: dict[str, Any],
    *,
    diff: dict[str, Any],
    tranche: str,
    manifest: Path,
    worklist: Path,
    dry_run: bool,
    aliases_path: Path,
    registry_path: Path,
    ocr_dir: Path,
    engine: str | None = None,
    force: bool = False,
    concurrency: int | None = None,
    cost_cap_usd: float | None = None,
) -> None:
    """Print the work-list (always) and, unless ``dry_run``, run scoped stages.

    A metadata-only tranche runs nothing, but still rewrites the PDF
    work-list (empty) -- a stale list from a prior tranche must never
    survive into this one. ``--dry-run`` still MATERIALIZES the work-list
    files (credential-free, no spend, no promotion) so a separately-invoked
    OCR step gets the right card set — the ``/ship-tranche`` flow relies on
    this. The non-dry spend path first enforces the ``preflight_ocr``
    verify-before-spend gate. ``cost_cap_usd`` overrides the
    embed cost cap.

    The PDF/IMG work-list is computed by
    ``pursue_index.ingest_scope.scope_worklist`` -- Class B, approved and
    unaddressed Class C, this tranche's approved renames, and any card whose
    registry bytes have drifted from its OCR sidecar's (R7C.1 / #168). Scope
    is computed from the tranche-diff + this tranche's own sha, never from
    reading back the (possibly not-yet-promoted) manifest on disk -- a dry
    run must be able to print the exact same scope a real run would, before
    anything is promoted (R7C.2 / #169).

    Writes two separate worklists:
      - worklist (e.g. data/ingest-worklist.txt) for PDF/IMG rows, tagged
        with each card's scope reason and headed with this tranche's sha --
        what every consumer actually validates the live manifest against
      - worklist-av (e.g. data/ingest-worklist-av.txt) for VID/AUD rows
    """
    tranche_sha = diff.get("tranche_sha256") or tranche
    scoped = scope_worklist(
        diff, tranche_sha,
        aliases_path=aliases_path, registry_path=registry_path, ocr_dir=ocr_dir,
    )
    av_card_ids = scoped_av_card_ids(summary)

    if estimate := ingest_estimate_text(diff, summary, card_ids=[s.card_id for s in scoped]):
        typer.echo("\n" + estimate)
    _print_worklists(scoped, av_card_ids)
    _write_and_run(
        scoped, av_card_ids,
        manifest=manifest, worklist=worklist, tranche_sha=tranche_sha, dry_run=dry_run,
        engine=engine, force=force, concurrency=concurrency, cost_cap_usd=cost_cap_usd,
    )

    av_steps = render_av_next_steps(summary)
    if av_steps:
        typer.echo("")
        typer.echo("\n".join(av_steps))
