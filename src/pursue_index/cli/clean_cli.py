"""``pursue clean`` sub-command surface.

Runs the LLM cleanup pass over OCR output. Split out of ``commands.py`` so
the option list (model, budget, pilot card filter) doesn't bloat the
parent module. Imports of the Anthropic SDK are deferred to the runner.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index import get_logger
from pursue_index.clean import TRANCHE_SPEND_CEILING_USD
from pursue_index.clean.runner import (
    BudgetExceededError,
    CardReport,
    run_card,
)
from pursue_index.cli.clean_qc_cli import clean_qc_app
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.text_control import console_text

log = get_logger(__name__)
console = Console()

clean_app = typer.Typer(
    name="clean",
    help="LLM cleanup pass over OCR output (pilot-gated).",
    no_args_is_help=True,
)


# Alignment: ``ops_cli`` uses a no-op callback to keep typer
# treating the sub-app as a multi-command group under both invocation
# paths (direct ``runner.invoke(clean_app, ...)`` in tests vs.
# ``app.add_typer(clean_app)`` in the parent CLI). Without this anchor,
# typer collapses single-command sub-apps into the root, so the
# invocation shape silently changes when ``clean`` later gets a second
# subcommand. See ``ops_cli.py`` for the canonical caveat.
@clean_app.callback()
def _clean_callback() -> None:
    """Anchor that forces typer to treat ``clean`` as a multi-command group."""
    return


# Attach the qc sub-app so ``pursue clean qc run`` works.
clean_app.add_typer(clean_qc_app)


# Default model: Haiku-4-5 per the plan. Cheaper than Sonnet by ~4x at
# the same prompt-cache hit rate and good enough for "fix obvious OCR
# errors" — verified via the pilot before any corpus-wide run.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# The clean pass runs under the shared tranche ceiling and fails closed at it:
# the run stops the moment the ceiling is reached rather than carrying on. Any
# run can set its own with --budget-usd. See ``pursue_index.clean`` for why the
# clean pass and its QC pass answer to the same value.
DEFAULT_BUDGET_USD = TRANCHE_SPEND_CEILING_USD


def _resolve_cards(
    manifest_path: Path,
    cards_filter: str | None,
    limit: int | None,
) -> list[str]:
    """Pick which card ids to clean, honoring --cards and --limit."""
    manifest = load_manifest(manifest_path)
    pdf_cards = [c.card_id for c in manifest.cards if c.asset_type == "PDF"]
    if cards_filter:
        wanted = {c.strip() for c in cards_filter.split(",") if c.strip()}
        pdf_cards = [c for c in pdf_cards if c in wanted]
    if limit is not None and limit >= 0:
        pdf_cards = pdf_cards[:limit]
    return pdf_cards


def _print_dry_run(card_ids: list[str], budget: float, model: str) -> None:
    """Surface the planned work without invoking the runner."""
    console.print(
        f"[yellow]DRY-RUN[/yellow]: would clean {len(card_ids)} cards "
        f"with model [bold]{model}[/bold] under a ${budget:.2f} cap."
    )
    for cid in card_ids[:10]:
        console.print(f"  - {console_text(cid)}")
    if len(card_ids) > 10:
        console.print(f"  ... and {len(card_ids) - 10} more")


def _print_summary(reports: list[CardReport], total_cost: float) -> None:
    """Print the per-card pilot summary table."""
    table = Table(title=f"Cleanup pass summary — ${total_cost:.4f}")
    table.add_column("card_id")
    table.add_column("cleaned", justify="right")
    table.add_column("skipped", justify="right")
    table.add_column("cost_usd", justify="right")
    table.add_column("in tok", justify="right")
    table.add_column("out tok", justify="right")
    for r in reports:
        table.add_row(
            console_text(r.card_id), str(r.pages_cleaned), str(r.pages_skipped),
            f"${r.cost_usd:.4f}",
            str(r.input_tokens), str(r.output_tokens),
        )
    console.print(table)


def _run_one_card(
    card_id: str,
    model: str,
    budget_usd: float,
    running_cost: float,
) -> CardReport:
    """Resolve sidecar paths for ``card_id`` and dispatch to ``run_card``."""
    pages_path = settings.ocr_dir / card_id / "pages.jsonl"
    sidecar_path = settings.ocr_dir / card_id / "pages_cleaned.jsonl"
    if not pages_path.exists():
        console.print(f"[yellow]skip[/yellow] {console_text(card_id)}: no pages.jsonl on disk")
        return CardReport(card_id, 0, 0, 0.0, 0, 0, 0)
    return run_card(
        card_id=card_id,
        pages_path=pages_path,
        sidecar_path=sidecar_path,
        model_id=model,
        budget_usd=budget_usd,
        running_cost_usd=running_cost,
    )


def _fold_partial_spend(
    exc: BudgetExceededError,
    reports: list[CardReport],
    running_cost: float,
) -> float:
    """Fold the in-progress card's partial spend into the summary.

    When ``BudgetExceededError`` fires mid-card, the in-progress card has
    already written pages to the sidecar and spent real dollars. Without
    this fold-in, the abort summary under-reports
    total spend and an operator may overspend on the next invocation.
    Returns the updated running-cost total.
    """
    partial = getattr(exc, "partial_cost_usd", 0.0)
    partial_card_id = getattr(exc, "card_id", "")
    if partial_card_id:
        reports.append(CardReport(
            card_id=partial_card_id,
            pages_cleaned=getattr(exc, "pages_cleaned", 0),
            pages_skipped=0,
            cost_usd=partial,
            input_tokens=0, output_tokens=0, cache_read_tokens=0,
        ))
    return running_cost + partial


@clean_app.command("run")
def clean_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    cards: str | None = typer.Option(
        None, "--cards",
        help="Comma-separated card_ids to clean. Defaults to every PDF card.",
    ),
    limit: int | None = typer.Option(
        None, "--limit",
        help="Hard cap on the number of cards processed (pilot use).",
    ),
    model: str = typer.Option(
        DEFAULT_MODEL, "--model",
        help="Anthropic model id. Default: claude-haiku-4-5.",
    ),
    budget_usd: float = typer.Option(
        DEFAULT_BUDGET_USD, "--budget-usd",
        help=(
            "Hard cost cap. Run aborts when cumulative cost exceeds this. "
            "Cap is checked after each page; up to one page's worth of "
            "cost may be incurred past the cap at card boundaries."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print the planned card list and exit without spending tokens.",
    ),
) -> None:
    """Run the cleanup pass. Idempotent per (text, model, prompt)."""
    settings.ensure_dirs()
    card_ids = _resolve_cards(manifest, cards, limit)
    if dry_run:
        _print_dry_run(card_ids, budget_usd, model)
        return
    reports: list[CardReport] = []
    running_cost = 0.0
    try:
        for cid in card_ids:
            report = _run_one_card(cid, model, budget_usd, running_cost)
            reports.append(report)
            running_cost += report.cost_usd
    except BudgetExceededError as exc:
        running_cost = _fold_partial_spend(exc, reports, running_cost)
        console.print(f"[red]BUDGET EXCEEDED[/red]: {exc}")
        _print_summary(reports, running_cost)
        raise typer.Exit(code=2)
    _print_summary(reports, running_cost)
    console.print(
        f"[green]done[/green]: {len(reports)} cards, ${running_cost:.4f} spent."
    )
