"""Typer app base and shared console for the ``pursue`` entry point."""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console

from pursue_index.paths import UntrustedRootError

console = Console()


class PursueApp(typer.Typer):
    """Reports an untrusted working directory as one line, not a traceback."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().__call__(*args, **kwargs)
        except UntrustedRootError as exc:
            typer.echo(f"refusing — {exc}", err=True)
            raise SystemExit(4) from None
