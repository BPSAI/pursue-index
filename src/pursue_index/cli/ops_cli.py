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


# Verification: ``embed_app`` next door also has a single
# command and no callback. It works because nothing invokes ``embed_app``
# directly — its tests all go through the parent ``app`` via
# ``app.add_typer(embed_app)``, which preserves the subcommand grouping.
# ``ops_app``'s tests DO invoke it directly (``runner.invoke(ops_app, ...)``)
# to keep them tightly scoped, and a single-command typer app DOES collapse
# its subcommand into the root invocation when run standalone. The callback
# below is the established mechanism to keep ``ops`` a multi-command group
# under both invocation paths.
@ops_app.callback()
def _ops_callback() -> None:
    """Anchor that forces typer to treat ``ops`` as a multi-command group."""
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
    re-parsing JSON. Both formats come from
    ``pdf_health.format_ok``/``format_fail`` so this CLI and the bare
    script (``scripts/pdf_health_check.py``) cannot drift apart:

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
        sentinel_fail = pdf_health.HealthFail(
            url="-",
            status=-1,
            error=f"sentinel:{type(exc).__name__}: {exc}",
        )
        print(pdf_health.format_fail(sentinel_fail), file=sys.stderr, flush=True)
        raise typer.Exit(code=1)

    result = pdf_health.check_pdf_health(str(sentinel.asset_url))
    if isinstance(result, pdf_health.HealthOk):
        print(pdf_health.format_ok(result), flush=True)
        return

    # HealthFail — emit on stderr so failures stay visible even if
    # stdout is consumed by a downstream pipe.
    print(pdf_health.format_fail(result), file=sys.stderr, flush=True)
    raise typer.Exit(code=1)
