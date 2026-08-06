"""`pursue provenance report` — Phase-A coverage summary (PV1.6).

A thin, read-only CLI over :mod:`pursue_index.provenance_report`. It runs the
resolution chain (Tier-0 sweep + era bucketing + identifier resolver) and prints
the coverage split: how many cards carry a prior-release claim, how many are
resolved by era alone, how many are unresolved, and how many are flagged for the
later page-image comparison. It publishes nothing — the optional ``--json-out``
is refused if it points anywhere under ``web/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index.provenance_report import (
    POSITIVE_TIER_PRECEDENCE,
    CoverageReport,
    build_report,
    load_catalogue,
)

console = Console()

provenance_app = typer.Typer(
    name="provenance",
    help="Provenance coverage report over the Phase-A resolution chain.",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


def _reject_web_path(path: Path) -> None:
    """Refuse any output path under ``web/`` — this command never publishes."""
    resolved = path.resolve()
    web_root = (_REPO_ROOT / "web").resolve()
    if resolved == web_root or web_root in resolved.parents:
        console.print(
            f"[red]error:[/red] this is a report-only command; it refuses to "
            f"write under web/ ({path})."
        )
        raise typer.Exit(code=2)


def _print_coverage(report: CoverageReport) -> None:
    """Render the headline split and the per-tier / per-era breakdowns."""
    table = Table(title=f"Provenance coverage — {report.card_count} cards")
    table.add_column("Resolution route")
    table.add_column("Cards", justify="right")
    table.add_row("prior-release claim (Tier-0 + identifier resolver)", str(report.resolved_by_claim))
    for tier in POSITIVE_TIER_PRECEDENCE:
        count = report.tier_counts.get(tier.value)
        if count:
            table.add_row(f"  · {tier.value}", str(count))
    table.add_row("era alone (2015+ no-prior-release)", str(report.resolved_by_era))
    table.add_row("unresolved", str(report.unresolved))
    console.print(table)
    console.print(
        f"Of {report.card_count} cards, [bold]{report.resolved_by_claim}[/bold] carry a "
        f"provenance claim; [bold]{report.page_image_flagged}[/bold] are flagged for "
        "page-image comparison (Phase B)."
    )


def _print_unresolved(report: CoverageReport) -> None:
    """List the unresolved cards, grouped by the era they sit in."""
    if not report.unresolved:
        console.print("[green]No unresolved cards — every card was resolved.[/green]")
        return
    console.print(
        f"\n[bold]{report.unresolved} unresolved[/bold] "
        f"(by era: {report.unresolved_by_era})"
    )
    for outcome in report.unresolved_cards():
        console.print(f"  [dim]{outcome.era}[/dim]  {outcome.card_id}  {outcome.title}")


@provenance_app.command("report")
def provenance_report_cmd(
    manifest: Path = typer.Option(
        _DEFAULT_MANIFEST,
        "--manifest",
        exists=True,
        dir_okay=False,
        help="Manifest to resolve. Defaults to data/manifests/latest.json.",
    ),
    json_out: Path = typer.Option(
        None,
        "--json-out",
        help="Optional path for the JSON summary. Never accepted under web/.",
    ),
) -> None:
    """Run the resolution chain and report Phase-A coverage. Report only."""
    if json_out is not None:
        _reject_web_path(json_out)
    report = build_report(json.loads(manifest.read_text()), load_catalogue(_REPO_ROOT))
    _print_coverage(report)
    _print_unresolved(report)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
        console.print(f"\n[green]✔[/green] summary written to {json_out}")
