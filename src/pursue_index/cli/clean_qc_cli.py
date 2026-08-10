"""``pursue clean qc`` sub-command surface.

Runs the LLM-judge QC pass over already-cleaned pages. Mirrors
``clean_cli.py``'s shape: --manifest, --cards, --limit, --budget-usd,
--model, --dry-run.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pursue_index import get_logger
from pursue_index.clean import TRANCHE_SPEND_CEILING_USD
from pursue_index.clean.qc import runner as qc_runner
from pursue_index.config import settings
from pursue_index.scrape import load_manifest
from pursue_index.text_control import console_text

log = get_logger(__name__)
console = Console()

clean_qc_app = typer.Typer(
    name="qc",
    help="LLM-judge quality-review pass over cleaned OCR.",
    no_args_is_help=True,
)


@clean_qc_app.callback()
def _qc_callback() -> None:
    """Anchor that forces typer to treat ``qc`` as a multi-command group."""
    return


# Judge model: Sonnet 4.6. Haiku 4.5 is the cheaper alternative but is
# unmeasured for judge quality, so the judge stays pinned here in code.
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"

# The QC pass grades every PDF card in the manifest, the same unit of work the
# clean pass covers, so it runs under the same tranche ceiling and fails closed
# at it. See ``pursue_index.clean`` for why the value is shared.
DEFAULT_BUDGET_USD = TRANCHE_SPEND_CEILING_USD


def _resolve_cards(
    manifest_path: Path, cards_filter: str | None, limit: int | None,
) -> list[str]:
    """Pick which card ids to grade. PDF cards only."""
    manifest = load_manifest(manifest_path)
    pdf_cards = [c.card_id for c in manifest.cards if c.asset_type == "PDF"]
    if cards_filter:
        wanted = {c.strip() for c in cards_filter.split(",") if c.strip()}
        pdf_cards = [c for c in pdf_cards if c in wanted]
    if limit is not None and limit >= 0:
        pdf_cards = pdf_cards[:limit]
    return pdf_cards


def _print_dry_run(card_ids: list[str], budget: float, model: str) -> None:
    console.print(
        f"[yellow]DRY-RUN[/yellow]: would grade {len(card_ids)} cards "
        f"with judge [bold]{model}[/bold] under a ${budget:.2f} cap."
    )
    for cid in card_ids[:10]:
        console.print(f"  - {console_text(cid)}")
    if len(card_ids) > 10:
        console.print(f"  ... +{len(card_ids) - 10} more")


def _print_summary(reports: list[qc_runner.CardQcReport], total_cost: float) -> None:
    table = Table(title=f"QC summary — ${total_cost:.4f} spent")
    table.add_column("Card")
    table.add_column("Graded", justify="right")
    table.add_column("Skipped (idem)", justify="right")
    table.add_column("Skipped (judge)", justify="right")
    table.add_column("Cost", justify="right")
    for r in reports:
        table.add_row(
            console_text(r.card_id), str(r.pages_graded), str(r.pages_skipped),
            str(r.pages_skipped_judge), f"${r.cost_usd:.4f}",
        )
    console.print(table)


def _run_one_card(card_id: str, model: str, budget_usd: float) -> qc_runner.CardQcReport:
    raw_path = settings.ocr_dir / card_id / "pages.jsonl"
    cleaned_path = settings.ocr_dir / card_id / "pages_cleaned.jsonl"
    qc_path = settings.ocr_dir / card_id / "pages_cleaned_qc.jsonl"
    if not cleaned_path.exists():
        console.print(
            f"[yellow]skip[/yellow] {console_text(card_id)}: no pages_cleaned.jsonl on disk"
        )
        return qc_runner.CardQcReport(
            card_id=card_id, pages_graded=0, pages_skipped=0,
            pages_skipped_judge=0, cost_usd=0.0,
            input_tokens=0, output_tokens=0,
        )
    return qc_runner.run_card(
        card_id=card_id, raw_path=raw_path, cleaned_path=cleaned_path,
        qc_path=qc_path, judge_model_id=model, budget_usd=budget_usd,
    )


@clean_qc_app.command("run")
def qc_run(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
    cards: str | None = typer.Option(
        None, "--cards",
        help="Comma-separated card_ids to grade. Defaults to every PDF card.",
    ),
    limit: int | None = typer.Option(
        None, "--limit",
        help="Hard cap on the number of cards processed (pilot use).",
    ),
    model: str = typer.Option(
        DEFAULT_JUDGE_MODEL, "--judge-model",
        help="Judge model id. Default: claude-sonnet-4-6.",
    ),
    budget_usd: float = typer.Option(
        DEFAULT_BUDGET_USD, "--budget-usd",
        help="Hard cost cap. Run aborts when cumulative cost exceeds this.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print the planned card list and exit without spending tokens.",
    ),
) -> None:
    """Run the LLM-judge QC pass. Idempotent per (raw, cleaned, model, prompt)."""
    settings.ensure_dirs()
    card_ids = _resolve_cards(manifest, cards, limit)
    if dry_run:
        _print_dry_run(card_ids, budget_usd, model)
        return
    reports: list[qc_runner.CardQcReport] = []
    total_cost = 0.0
    try:
        for cid in card_ids:
            report = _run_one_card(cid, model, budget_usd - total_cost)
            reports.append(report)
            total_cost += report.cost_usd
    except qc_runner.QcBudgetExceededError as exc:
        console.print(f"[red]BUDGET EXCEEDED[/red]: {exc}")
        _print_summary(reports, total_cost + exc.partial_cost_usd)
        raise typer.Exit(code=2)
    _print_summary(reports, total_cost)
    console.print(
        f"[green]done.[/green] graded "
        f"{sum(r.pages_graded for r in reports)} pages"
    )
