"""``pursue tranche autopilot`` -- unattended local promote of a metadata-only tranche.

Thin glue over ``pursue_index.tranche_autopilot``: resolve the checkout, build
the child environment, run, exit with the engine's code (10/20/21/30/40; see
``tranche_autopilot.outcome``). Nothing here or in the engine publishes: the
result JSON lists the commands a human runs to push and merge.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

import pursue_index
from pursue_index.paths import UntrustedRootError, repo_root
from pursue_index.tranche_autopilot import child_env

tranche_app = typer.Typer(name="tranche", help="Tranche release automation (local only).")

_OPT_TRANCHE = typer.Option(..., "--tranche", help="Tranche csv_sha256 (64 lowercase hex).")
_OPT_RESULT = typer.Option(..., "--result", help="Where to write the result JSON "
                           "(outside the checkout).")
_OPT_REPO_ROOT = typer.Option(None, "--repo-root", help="The pursue-index checkout to "
                              "promote in (default: the resolved repo root).")


def _child_env() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """``(base, storage, ssh)``: the allowlisted environment every child gets,
    with this package's source as PYTHONPATH so every child ``pursue``/``make``
    runs the same code; the storage credentials for `storage verify`; and the
    SSH agent for the freshness recheck's fetch."""
    src = str(Path(pursue_index.__file__).resolve().parents[1])
    return (child_env.base_env(os.environ, src), child_env.storage_env(os.environ),
            child_env.ssh_env(os.environ))


@tranche_app.command("autopilot")
def autopilot_cmd(
    tranche: str = _OPT_TRANCHE,
    result: Path = _OPT_RESULT,
    root: Path | None = _OPT_REPO_ROOT,
) -> None:
    """Approve, gate and promote a metadata-only tranche, then commit locally.

    Exit codes: 10 done (operator pushes/merges), 20 needs the attended
    release, 21 ineligible or superseded, 30 a gate failed, 40 a precondition
    is missing. The result JSON is written on every exit.
    """
    # Imported here: the engine reads ``cli.worklist``, and ``cli/__init__``
    # loads this module while building the app, so a top-level import cycles.
    from pursue_index.tranche_autopilot.engine import (
        AutopilotConfig,
        refuse_without_checkout,
        run_autopilot,
    )
    from pursue_index.tranche_autopilot.runner import SubprocessRunner

    try:
        checkout = (root or repo_root()).resolve()
    except UntrustedRootError as exc:
        typer.echo(f"refusing -- {exc}", err=True)
        raise typer.Exit(refuse_without_checkout(tranche, result, str(exc))) from exc
    base_env, storage_env, ssh_env = _child_env()
    code = run_autopilot(AutopilotConfig(
        tranche_sha=tranche, result_path=result, repo_root=checkout,
        runner=SubprocessRunner(), env=base_env, storage_env=storage_env, ssh_env=ssh_env,
    ))
    typer.echo(f"autopilot exit {code}; result -> {result}")
    raise typer.Exit(code)
