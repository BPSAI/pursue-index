"""``pursue vision run`` — the vision observation stage (pipeline stage 6).

Split out of ``commands.py`` (same rationale as ``embed_cli`` / ``ops_cli``) to
keep that module under its size budget. ``commands.py`` re-attaches
``vision_app``.

Default run is the **verify-before-spend preflight**: select eligible items
(IMG-card assets + image-only PDF pages), diff against produced sidecars, print
the eligible-vs-produced report, and exit non-zero on a coverage shortfall — no
API calls.

Live work is reached only by asking for it, and the three ways of asking are
distinct:

* ``--live-smoke <card_id>`` examines exactly one card, so the generator can be
  smoke-tested end-to-end against a single image.
* ``--run`` is the operator-attended bulk pass: it examines every eligible item
  in the worklist, skips-and-counts an item it cannot examine, and reports
  produced-vs-eligible, exiting non-zero on a shortfall. This is how the
  uncovered image content gets its observations.
* ``--live --budget-usd X`` is the unattended counterpart to ``--run``: the
  same bulk examination, but bounded by a dollar cap so it can run without an
  operator watching it spend. It refuses to start under CI (``CI`` set in the
  environment) — CI never passes it — and refuses unless ``--confirm-live``
  is also given, so the spend is always named in the invocation itself.

Naming more than one of the three is ambiguous and refused. Naming none of
them means no API call is made, which is what an unattended caller gets by
default.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

from pursue_index.cli.worklist import (
    WorklistTrancheError,
    exit_on_tranche_error,
    worklist_card_ids,
)
from pursue_index.config import settings
from pursue_index.config.project_root import resolve_relative_data_root
from pursue_index.scrape import load_manifest
from pursue_index.vision import client, render
from pursue_index.vision.eligibility import EligibleItem, select_eligible
from pursue_index.vision.run import VisionRunReport, preflight_coverage, run_vision

vision_app = typer.Typer(name="vision", help="Vision observations for image content.")
console = Console()

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_WORKLIST = typer.Option(
    None, "--worklist", exists=True, dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "cover the full manifest (the escape hatch).",
)
_OBSERVATIONS_SUBPATH = Path("web") / "src" / "data" / "image-observations"


def default_observations_dir() -> Path:
    """The sidecar directory, anchored to the checkout it belongs to.

    The sidecars are committed inside the checkout, so this answer has to be
    the same wherever the CLI is invoked from: a run started in a subdirectory
    must see the sidecars a run started at the root sees. Resolution uses the
    same anchor the data root uses (``config.project_root``) — the project
    sentinel beside this package, identity-checked — and falls back to the
    working directory when the package is installed rather than checked out,
    which is the same answer a relative default has always given there.
    """
    import pursue_index

    return resolve_relative_data_root(
        _OBSERVATIONS_SUBPATH,
        package_dir=Path(pursue_index.__file__).parent,
        cwd=Path.cwd(),
    )


_OPT_OUT = typer.Option(
    None, "--out",
    help="Directory of per-card observation sidecars (<card_id>.json). "
    "Defaults to the checkout's image-observations directory.",
)
_OPT_LIVE_SMOKE = typer.Option(
    None, "--live-smoke",
    help="A LIVE PATH. Examine exactly one card_id via the vision model and "
    "write its sidecar — a single-image smoke test. CI never passes this.",
)
_OPT_RUN = typer.Option(
    False, "--run",
    help="A LIVE PATH. Operator-attended bulk pass: examine every eligible item "
    "in the worklist and write its observations. Omit to preview coverage only.",
)
_OPT_LIVE = typer.Option(
    False, "--live",
    help="A LIVE PATH. Unattended bulk pass under --budget-usd: examine "
    "eligible items until the worklist is covered or the next call would "
    "exceed the budget. Refused under CI, and refused unless --confirm-live "
    "is also given.",
)
_OPT_CONFIRM_LIVE = typer.Option(
    False, "--confirm-live",
    help="Required with --live: the explicit statement that this invocation "
    "means to spend, so a stray or scheduled command line cannot.",
)
_OPT_BUDGET = typer.Option(
    None, "--budget-usd",
    help="Hard cost cap for --live. Required with --live. Spend is metered "
    "from each response's reported usage at the model's rates, and the run "
    "stops before any call whose worst case would not fit in what is left.",
)


def _print_report(report: VisionRunReport) -> None:
    console.print(
        f"[cyan]vision coverage:[/cyan] {len(report.produced)} produced / "
        f"{len(report.eligible)} eligible"
    )
    if report.failures:
        console.print(
            f"[red]![/red] {len(report.failures)} item(s) could not be examined "
            f"and were skipped:"
        )
        for (card_id, row_key, page), reason in report.failures:
            console.print(f"  [red]-[/red] {_unit_label(card_id, row_key, page)}: {reason}")
    if report.empty:
        console.print(
            f"[red]![/red] {len(report.empty)} item(s) were examined but described "
            f"nothing and remain uncovered:"
        )
        for card_id, row_key, page in report.empty:
            console.print(f"  [red]-[/red] {_unit_label(card_id, row_key, page)}")
    if report.missing:
        console.print(
            f"[red]![/red] {len(report.missing)} eligible item(s) have no "
            f"observation sidecar (operator-attended vision run required):"
        )
        for card_id, row_key, page in sorted(report.missing):
            console.print(f"  [red]-[/red] {_unit_label(card_id, row_key, page)}")


def _unit_label(card_id: str, row_key: str, page: int) -> str:
    """One coverage unit, naming its row only when the card_id has more than one."""
    return f"{card_id}{f' [{row_key}]' if row_key else ''} p{page}"


def _examine(
    items: list[EligibleItem], out: Path, *, budget_usd: float | None = None
) -> VisionRunReport:
    """Drive the live vision client over ``items``, writing their sidecars."""
    return run_vision(
        items, out,
        examine_fn=client.examine_image,
        load_image_fn=render.load_image_for,
        budget_usd=budget_usd,
    )


def _run_live_smoke(items: list[EligibleItem], out: Path, card_id: str) -> None:
    """Examine a single card (the smoke target) via the live vision client."""
    scoped = [i for i in items if i.card_id == card_id]
    if not scoped:
        console.print(f"[red]error:[/red] {card_id!r} is not an eligible item.")
        raise typer.Exit(code=2)
    report = _examine(scoped, out)
    console.print(
        f"[green]✔[/green] live-smoke examined {len(scoped)} item(s) for {card_id}"
    )
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


def _run_bulk(items: list[EligibleItem], out: Path) -> None:
    """Examine every eligible item, then gate on produced-vs-eligible.

    Per-item trouble is skipped and counted rather than aborting the pass, so
    one unreadable asset cannot cost the rest of the run. Anything skipped stays
    outstanding in the coverage report, which is what the exit code reflects.
    """
    console.print(
        f"[cyan]vision run:[/cyan] examining {len(items)} eligible item(s)"
    )
    report = _examine(items, out)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


def _run_live(items: list[EligibleItem], out: Path, budget_usd: float) -> None:
    """Examine eligible items unattended, stopping before the budget is exceeded.

    Sidecars land as each card is committed, so a budget stop still keeps
    every card examined before it.
    """
    console.print(
        f"[cyan]vision run (live):[/cyan] examining up to {len(items)} eligible "
        f"item(s) under a ${budget_usd:.2f} budget"
    )
    report = _examine(items, out, budget_usd=budget_usd)
    console.print(
        f"[cyan]vision spend:[/cyan] ${report.spent_usd:.4f} metered of "
        f"${budget_usd:.2f}"
    )
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


def _check_live_preconditions(
    run: bool,
    live_smoke: str | None,
    live: bool,
    budget_usd: float | None,
    confirm_live: bool = False,
) -> None:
    """Refuse an ambiguous or unsafe live invocation before any work starts."""
    named = [
        flag for flag, chosen in
        (("--run", run), ("--live-smoke", bool(live_smoke)), ("--live", live))
        if chosen
    ]
    if len(named) > 1:
        console.print(
            f"[red]error:[/red] {' and '.join(named)} are separate live paths; "
            "choose one."
        )
        raise typer.Exit(code=2)
    if not live:
        return
    if os.environ.get("CI"):
        console.print(
            "[red]error:[/red] --live is refused under CI; it is an unattended "
            "spend path and CI never passes it."
        )
        raise typer.Exit(code=2)
    if budget_usd is None:
        console.print("[red]error:[/red] --live requires --budget-usd.")
        raise typer.Exit(code=2)
    if not confirm_live:
        console.print(
            "[red]error:[/red] --live spends unattended; add --confirm-live "
            "to say you mean it."
        )
        raise typer.Exit(code=2)


@vision_app.command("run")
def vision_run(
    manifest: Path = _OPT_MANIFEST,
    worklist: Path = _OPT_WORKLIST,
    out: Path = _OPT_OUT,
    live_smoke: str = _OPT_LIVE_SMOKE,
    run: bool = _OPT_RUN,
    live: bool = _OPT_LIVE,
    budget_usd: float = _OPT_BUDGET,
    confirm_live: bool = _OPT_CONFIRM_LIVE,
) -> None:
    """Preview coverage by default; examine images only with --run, --live-smoke,
    or --live.

    Default: no spend — reports eligible-vs-produced and exits non-zero on a
    shortfall so a release gate can block on uncovered image content.
    """
    _check_live_preconditions(run, live_smoke, live, budget_usd, confirm_live)

    m = load_manifest(manifest)
    try:
        ids = worklist_card_ids(worklist, promoted_sha=m.csv_sha256)
    except WorklistTrancheError as exc:
        exit_on_tranche_error(exc)
    items = select_eligible(m, ids, settings.ocr_dir)
    out = out or default_observations_dir()

    if live_smoke:
        _run_live_smoke(items, out, live_smoke)
        return
    if run:
        _run_bulk(items, out)
        return
    if live:
        _run_live(items, out, budget_usd)
        return

    report = preflight_coverage(items, out)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
