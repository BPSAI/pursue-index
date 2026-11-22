"""Live-path helpers for ``pursue vision run`` (split from ``vision_cli``).

The coverage report printer, the three bulk/smoke/budgeted examination paths,
the ``--redescribe`` planner/preflight, and the precondition gate that refuses
an ambiguous or unsafe live invocation before any work starts.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console

from pursue_index.cli.vision_exceptions import check_method_exceptions
from pursue_index.scrape.types import Manifest
from pursue_index.vision import client, render
from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.redescribe import (
    estimate_cost_usd,
    plan_redescribe,
    redescribe_vision,
    worst_case_usd,
)
from pursue_index.vision.run import VisionRunReport, run_vision

console = Console()


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


def _require_client() -> None:
    """Build the vision client before any reservation; refuse the run if it cannot be."""
    try:
        client.require_client()
    except client.VisionClientError as exc:
        console.print(f"[red]error:[/red] vision client unavailable: {exc}")
        raise typer.Exit(code=1) from exc


def _spend_line(report: VisionRunReport, budget_usd: float) -> str:
    """The cap's ceiling-metered figure, with the list-price estimate beside it."""
    listed = (
        f" (≈ ${report.spent_list_usd:.4f} at list)"
        if report.spent_list_usd is not None else ""
    )
    return (
        f"[cyan]vision spend:[/cyan] ${report.spent_usd:.4f} metered at ceiling "
        f"rates{listed} of ${budget_usd:.2f}"
    )


def _examine(
    items: list[EligibleItem], out: Path, *, budget_usd: float | None = None
) -> VisionRunReport:
    """Drive the live vision client over ``items``, writing their sidecars."""
    _require_client()
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
    console.print(_spend_line(report, budget_usd))
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


def _check_live_preconditions(
    run: bool,
    live_smoke: str | None,
    live: bool,
    budget_usd: float | None,
    confirm_live: bool = False,
    redescribe: bool = False,
    worklist: Path | None = None,
) -> None:
    """Refuse an ambiguous or unsafe live invocation before any work starts.

    ``--redescribe`` shares ``--live``'s CI and budget gates, but its
    ``--confirm-live`` is checked later: without it the mode is a no-spend
    preflight rather than a refusal.
    """
    named = [
        flag for flag, chosen in
        (("--run", run), ("--live-smoke", bool(live_smoke)), ("--live", live),
         ("--redescribe", redescribe))
        if chosen
    ]
    if len(named) > 1:
        console.print(
            f"[red]error:[/red] {' and '.join(named)} are separate live paths; "
            "choose one."
        )
        raise typer.Exit(code=2)
    if not (live or redescribe):
        return
    flag = "--live" if live else "--redescribe"
    if os.environ.get("CI"):
        console.print(
            f"[red]error:[/red] {flag} is refused under CI; it is a spend "
            "path and CI never passes it."
        )
        raise typer.Exit(code=2)
    if redescribe and worklist is None:
        console.print("[red]error:[/red] --redescribe requires --worklist.")
        raise typer.Exit(code=2)
    if budget_usd is None:
        console.print(f"[red]error:[/red] {flag} requires --budget-usd.")
        raise typer.Exit(code=2)
    if live and not confirm_live:
        console.print(
            "[red]error:[/red] --live spends unattended; add --confirm-live "
            "to say you mean it."
        )
        raise typer.Exit(code=2)


def _run_redescribe(
    manifest: Manifest, ids: set[str], out: Path, budget_usd: float,
    confirm_live: bool, exception_override: tuple[bool, str | None] = (False, None),
) -> None:
    """Plan a re-describe; refuse what cannot run; preflight or spend."""
    check_method_exceptions(ids, *exception_override)
    plan = plan_redescribe(manifest, ids, out)
    if plan.refusals:
        console.print(
            f"[red]error:[/red] --redescribe refused; {len(plan.refusals)} "
            "problem(s), nothing examined:"
        )
        for reason in plan.refusals:
            console.print(f"  [red]-[/red] {reason}")
        raise typer.Exit(code=2)
    estimate = estimate_cost_usd(plan.page_count)
    ceiling = worst_case_usd(plan.page_count)
    console.print(
        f"[cyan]vision redescribe:[/cyan] {plan.card_count} card(s) / "
        f"{plan.page_count} page(s) with {client.VISION_MODEL}"
    )
    console.print(
        f"[cyan]estimated cost:[/cyan] ${estimate:.2f} typical "
        f"(worst-case ceiling ${ceiling:.2f}) against a ${budget_usd:.2f} budget"
    )
    if estimate > budget_usd:
        console.print("[red]error:[/red] the estimate exceeds --budget-usd.")
        raise typer.Exit(code=1)
    if not confirm_live:
        console.print("[yellow]preflight only:[/yellow] no calls made; add --confirm-live to spend.")
        return
    _require_client()
    report = redescribe_vision(
        plan, out,
        examine_fn=client.examine_image, load_image_fn=render.load_image_for,
        budget_usd=budget_usd,
    )
    console.print(_spend_line(report, budget_usd))
    console.print(
        f"[cyan]redescribed:[/cyan] {len(report.produced)} / {len(report.eligible)} page(s)"
    )
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
