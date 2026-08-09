"""``pursue vision run`` — the vision observation stage (pipeline stage 7).

Split out of ``commands.py`` (same rationale as ``embed_cli`` / ``ops_cli``) to
keep that module under its size budget. ``commands.py`` re-attaches
``vision_app``.

Default run is the **verify-before-spend preflight**: select eligible items
(IMG-card assets + image-only PDF pages), diff against produced sidecars, print
the eligible-vs-produced report, and exit non-zero on a coverage shortfall — no
API calls. ``--live-smoke <card_id>`` is the ONLY live path: it examines a
single card so the generator can be smoke-tested end-to-end without corpus
spend. The bulk backfill of uncovered cards is an operator-attended run.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pursue_index.cli.worklist import worklist_card_ids
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.vision import client, render
from pursue_index.vision.eligibility import select_eligible
from pursue_index.vision.run import VisionRunReport, preflight_coverage, run_vision

vision_app = typer.Typer(name="vision", help="Vision observations for image content.")
console = Console()

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_WORKLIST = typer.Option(
    None, "--worklist", exists=True, dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "cover the full manifest (the escape hatch).",
)
_OPT_OUT = typer.Option(
    Path("web/src/data/image-observations"), "--out",
    help="Directory of per-card observation sidecars (<card_id>.json).",
)
_OPT_LIVE_SMOKE = typer.Option(
    None, "--live-smoke",
    help="THE ONLY LIVE PATH. Examine exactly one card_id via the vision model "
    "and write its sidecar — a single-image smoke test. CI never passes this.",
)


def _print_report(report: VisionRunReport) -> None:
    console.print(
        f"[cyan]vision coverage:[/cyan] {len(report.produced)} produced / "
        f"{len(report.eligible)} eligible"
    )
    if report.missing:
        console.print(
            f"[red]![/red] {len(report.missing)} eligible item(s) have no "
            f"observation sidecar (operator-attended vision spend required):"
        )
        for card_id, page in sorted(report.missing):
            console.print(f"  [red]-[/red] {card_id} p{page}")


def _run_live_smoke(items: list, out: Path, card_id: str) -> None:
    """Examine a single card (the smoke target) via the live vision client."""
    scoped = [i for i in items if i.card_id == card_id]
    if not scoped:
        console.print(f"[red]error:[/red] {card_id!r} is not an eligible item.")
        raise typer.Exit(code=2)
    report = run_vision(
        scoped, out,
        examine_fn=client.examine_image,
        load_image_fn=render.load_image_for,
    )
    console.print(
        f"[green]✔[/green] live-smoke wrote {len(scoped)} page(s) for {card_id}"
    )
    _print_report(report)


@vision_app.command("run")
def vision_run(
    manifest: Path = _OPT_MANIFEST,
    worklist: Path = _OPT_WORKLIST,
    out: Path = _OPT_OUT,
    live_smoke: str = _OPT_LIVE_SMOKE,
) -> None:
    """Preflight coverage (default) or a single-card live smoke (``--live-smoke``).

    Default: no spend — reports eligible-vs-produced and exits non-zero on a
    shortfall so a release gate can block on uncovered image content.
    """
    m = load_manifest(manifest)
    ids = worklist_card_ids(worklist)
    items = select_eligible(m, ids, settings.ocr_dir)

    if live_smoke:
        _run_live_smoke(items, out, live_smoke)
        return

    report = preflight_coverage(items, out)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
