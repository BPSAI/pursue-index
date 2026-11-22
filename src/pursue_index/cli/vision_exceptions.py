"""The ``--redescribe`` gate for cards listed as a method exception.

Split from ``vision_live``: refuses listed cards by name unless the operator
overrides with a stated reason, and refuses outright when the list cannot be read.
"""

from __future__ import annotations

from typing import NoReturn

import typer
from rich.console import Console

from pursue_index import get_logger
from pursue_index.vision.method_exceptions import MethodExceptionsError, load_method_exceptions

console = Console()
log = get_logger(__name__)


def _refuse(lines: list[str]) -> NoReturn:
    for line in lines:
        console.print(line)
    raise typer.Exit(code=2)


def check_method_exceptions(
    ids: set[str], override: bool, reason: str | None
) -> None:
    """Refuse listed curated cards unless overridden with a stated reason."""
    why = (reason or "").strip()
    if override != bool(reason is not None) or (override and not why):
        _refuse(["[red]error:[/red] --override-method-exception and --reason go together, "
                 "and the reason must say something."])
    try:
        listed = {e.card_id: e for e in load_method_exceptions()}
    except MethodExceptionsError as exc:
        _refuse([f"[red]error:[/red] --redescribe refused; the method exceptions cannot "
                 f"be read, so none can be ruled out: {exc}"])
    hit = [listed[c] for c in sorted(ids) if c in listed]
    if not hit:
        return
    if not override:
        _refuse([f"[red]error:[/red] --redescribe refused; {len(hit)} listed card(s) are a "
                 "method exception and stay on their curated pass, nothing examined:"]
                + [f"  [red]-[/red] {e.card_id}: {e.reason} ({e.cluster_label}, "
                   f"decided {e.decided_at})" for e in hit]
                + ["  add --override-method-exception --reason \"<text>\" to re-describe "
                   "them anyway."])
    console.print(
        f"[yellow]method exception overridden[/yellow] for {len(hit)} card(s): {why}"
    )
    for e in hit:
        console.print(f"  [yellow]-[/yellow] {e.card_id} ({e.reason})")
    log.warning("vision.redescribe.exception_overridden", reason=why,
                card_ids=[e.card_id for e in hit])
