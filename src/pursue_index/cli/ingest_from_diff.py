"""``pursue ingest run --from-diff`` work-list export + scoped-stage driver (T6.6).

The operator's one-command path after a ``needs-review`` tranche clears the
gate: turn the tranche-diff into the scoped card-set, show it (``--dry-run``)
or run it (download -> ocr -> embed via the T6.5 ``--worklist`` path).

Work-list contents: the union of ``summarize_ingest_work``'s
``needs_download`` / ``needs_ocr`` / ``needs_embed`` lists, de-duplicated with
first-seen order preserved. Those three lists are the same Class-B set today
(each stage depends on the prior stage's output for the same new-asset cards),
but unioning is forward-safe if they ever diverge -- and each scoped executor
already skips-if-exists internally, so a superset work-list is harmless. The
file format is the plain ``card_id``-per-line contract the T6.5 executors read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer


def scoped_card_ids(summary: dict[str, Any]) -> list[str]:
    """Union of needs_download/needs_ocr/needs_embed, first-seen order kept."""
    ordered: list[str] = []
    seen: set[str] = set()
    for key in ("needs_download", "needs_ocr", "needs_embed"):
        for cid in summary.get(key, []) or []:
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
    return ordered


def write_worklist_file(path: Path, card_ids: list[str], tranche: str) -> None:
    """Write the scoped card_ids to ``path`` (one per line, with a header)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# worklist for tranche {tranche[:12]} (pursue ingest run --from-diff)",
        f"# {len(card_ids)} card_id(s) scoped from the tranche-diff",
        *card_ids,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_scoped_stages(manifest: Path, worklist: Path, *, cost_cap_usd: float | None = None) -> None:
    """Drive download -> ocr -> embed scoped to ``worklist`` (T6.5 executors).

    Calls the executor functions directly (rather than shelling out) so the
    real ``--worklist`` subsetting runs and the deep stage functions remain
    monkeypatch-able in tests. The non-cost-cap embed defaults are sourced from
    ``embed_cli``'s own ``typer.Option`` defaults (single source of truth — they
    can't silently diverge from a manual ``pursue embed run``). ``cost_cap_usd``
    is the operator escape hatch for a large tranche; ``None`` uses the embed
    default.
    """
    from pursue_index.cli import embed_cli
    from pursue_index.cli.download_ocr_cli import download_run, ocr_run

    cap = cost_cap_usd if cost_cap_usd is not None else embed_cli._OPT_COST_CAP.default
    download_run(manifest=manifest, worklist=worklist)
    ocr_run(
        manifest=manifest,
        engine=None,
        force=False,
        concurrency=None,
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
        augment_from=None,
        augment_miss_rate_threshold=embed_cli._OPT_MISS_RATE.default,
        image_observations_index=embed_cli._OPT_IMAGE_OBS_INDEX.default,
        worklist=worklist,
    )


def execute_from_diff(
    summary: dict[str, Any],
    *,
    tranche: str,
    manifest: Path,
    worklist: Path,
    dry_run: bool,
    cost_cap_usd: float | None = None,
) -> None:
    """Print the work-list (always) and, unless ``dry_run``, run scoped stages.

    A metadata-only tranche (empty work-list) prints a notice and runs nothing
    even without ``--dry-run`` -- there is no new content to OCR/embed.
    ``cost_cap_usd`` overrides the embed stage's cost cap (operator escape hatch
    for a large tranche).
    """
    card_ids = scoped_card_ids(summary)
    typer.echo("")
    typer.echo(f"work-list ({len(card_ids)} card_id(s) to download/ocr/embed):")
    for cid in card_ids:
        typer.echo(f"  {cid}")
    if not card_ids:
        typer.echo("  (none -- metadata-only tranche; no scoped stages to run)")
        return
    if dry_run:
        typer.echo("")
        typer.echo("--dry-run: stages NOT executed. Re-run without --dry-run to ingest.")
        return
    write_worklist_file(worklist, card_ids, tranche)
    typer.echo("")
    typer.echo(f"wrote work-list -> {worklist}; running scoped download -> ocr -> embed")
    run_scoped_stages(manifest, worklist, cost_cap_usd=cost_cap_usd)
