"""Operations / health-check CLI subcommands.

Split out of ``commands.py`` so the main CLI module stays under the
file-size budget. Currently exposes ``pursue ops pdf-health``, which
the 6h cron poll workflow runs alongside its CSV check to catch
PDF-only Akamai gating shifts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from pursue_index import get_logger
from pursue_index.config import settings
from pursue_index.scrape import pdf_health

log = get_logger(__name__)

ops_app = typer.Typer(
    name="ops",
    help="Operations / health checks driven by GitHub Actions cron jobs.",
    no_args_is_help=True,
)


@ops_app.callback()
def _ops_callback() -> None:
    """Anchor that forces typer to treat ``ops`` as a multi-command group.

    Without an explicit callback, a single-command typer app collapses
    its subcommand into the root invocation, which would silently rename
    ``pursue ops pdf-health`` to ``pursue ops`` and break the workflow.
    """
    # No-op by design — the callback's existence is what matters.
    return


@ops_app.command("pdf-health")
def pdf_health_cmd(
    manifest: Path = typer.Option(
        None,
        "--manifest",
        help="Manifest path. Defaults to data/manifests/latest.json.",
    ),
) -> None:
    """Fetch a sentinel PDF (deterministically picked) and exit 0/1.

    Designed to be wired into ``poll-pursue.yml`` after the CSV check.
    Output is two stable line formats so the workflow can grep without
    re-parsing JSON:

    * ``pdf-health.ok url=<url> bytes=<n>``  (exit 0)
    * ``pdf-health.fail url=<url> status=<n> error=<msg>``  (exit 1)
    """
    manifest_path = manifest or (settings.manifests_dir / "latest.json")

    try:
        sentinel = pdf_health.pick_sentinel(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        # No sentinel = the cron has nothing to check. Treat as failure
        # so the operator gets paged — silent green here would mask a
        # real problem (manifest never built, or all-VID manifest).
        print(
            f"pdf-health.fail url=- status=-1 error=sentinel:{type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise typer.Exit(code=1)

    result = pdf_health.check_pdf_health(str(sentinel.asset_url))
    if isinstance(result, pdf_health.HealthOk):
        print(f"pdf-health.ok url={result.url} bytes={result.bytes_received}", flush=True)
        return

    # HealthFail — emit on stderr so failures stay visible even if
    # stdout is consumed by a downstream pipe.
    print(
        f"pdf-health.fail url={result.url} status={result.status} error={result.error}",
        file=sys.stderr,
        flush=True,
    )
    raise typer.Exit(code=1)
