"""`pursue storage verify` — preflight the 3-tier storage-durability contract.

Thin glue over ``pursue_index.storage.contract`` (all logic + the same-account
finding live there). Exits non-zero if any tier (NAS / main R2 / backup R2) is
not configured, so the operator's ship path can gate on it before a release.
Credential-free: checks env-key presence only, never reads secret values.
"""

from __future__ import annotations

import os

import typer

from pursue_index.storage.contract import (
    render_contract_summary,
    verify_storage_contract,
)

storage_app = typer.Typer(
    name="storage",
    help="Archive storage-durability contract (NAS + main R2 + backup R2).",
)


@storage_app.command("verify")
def verify_cmd() -> None:
    """Verify all three storage tiers are configured; surface the DR risk.

    Exit 0 iff every tier resolves its configuring env keys. The same-account
    backup risk is printed as a WARNING but does not fail the check (it is a
    durability-posture finding needing an operator decision, not a
    misconfiguration).
    """
    result = verify_storage_contract(os.environ)
    typer.echo(render_contract_summary(result))
    raise typer.Exit(0 if result.ok else 1)


def main() -> None:
    storage_app()


if __name__ == "__main__":
    main()
