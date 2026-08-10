"""Rendering for ``pursue scrape run`` — the manifest summary and the diff.

Split out of ``commands.py`` for the same reason as ``embed_cli``/``ops_cli``:
the sub-app file stays a thin surface over the pipeline stages. What is rendered
here is entirely corpus text — card titles, agency names, asset types read
straight from the government's CSV — so every value goes through
:func:`~pursue_index.text_control.console_text` and, where it is interpolated
into a markup-bearing string, through ``rich``'s own escaping as well.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from pursue_index.text_control import console_text

__all__ = [
    "print_manifest_summary",
    "print_scrape_diff",
]

console = Console()


def print_scrape_diff(diff: dict[str, Any]) -> None:
    """Render the rotate / added / removed summary lines for ``scrape run``.

    Removals are the loud line: they are the canonical signal that an upstream
    quiet-pull happened, and each one names a card by its CSV title.
    """
    if diff["snapshot"]:
        console.print(f"[dim]Prior manifest rotated to snapshot:[/dim] {diff['snapshot']}")
    if diff["added"]:
        console.print(f"[cyan]+[/cyan] {diff['added']} new card(s)")
    if diff["removed"]:
        console.print(
            f"[red]![/red] [bold]{diff['removed']} card(s) REMOVED "
            f"upstream[/bold] — logged to data/removed-cards.jsonl"
        )
        for title in diff["removed_titles"]:
            console.print(f"  - {console_text(title)}", markup=False, highlight=False)


def _counts_table(title: str, column: str, counts: dict[str, int]) -> Table:
    """A two-column count table, most numerous first, labels rendered as text."""
    table = Table(title=title)
    table.add_column(column)
    table.add_column("Count", justify="right")
    for label, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        table.add_row(console_text(label), str(count))
    return table


def print_manifest_summary(manifest: Any) -> None:
    """Render the per-agency and per-asset-type breakdown of a fresh manifest."""
    by_agency: dict[str, int] = {}
    by_type: dict[str, int] = {}
    redacted = 0
    for card in manifest.cards:
        by_agency[card.agency] = by_agency.get(card.agency, 0) + 1
        by_type[card.asset_type] = by_type.get(card.asset_type, 0) + 1
        if card.redacted:
            redacted += 1

    console.print(
        _counts_table(f"Manifest summary — {manifest.card_count} cards", "Agency", by_agency)
    )
    console.print(_counts_table("By asset type", "Type", by_type))
    console.print(f"Redacted: [bold]{redacted}[/bold] / {manifest.card_count}")
