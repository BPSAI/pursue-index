"""``pursue vision run`` — the vision observation stage (pipeline stage 6).

Split out of ``commands.py`` (same rationale as ``embed_cli`` / ``ops_cli``) to
keep that module under its size budget. ``commands.py`` re-attaches
``vision_app``.

Default run is the **verify-before-spend preflight**: select eligible items
(IMG-card assets + image-only PDF pages), diff against produced sidecars, print
the eligible-vs-produced report, and exit non-zero on a coverage shortfall — no
API calls.

Live work is reached only by asking for it, and the three ways of asking are
distinct:

* ``--live-smoke <card_id>`` examines exactly one card, so the generator can be
  smoke-tested end-to-end against a single image.
* ``--run`` is the operator-attended bulk pass: it examines every eligible item
  in the worklist, skips-and-counts an item it cannot examine, and reports
  produced-vs-eligible, exiting non-zero on a shortfall. This is how the
  uncovered image content gets its observations.
* ``--live --budget-usd X`` is the unattended counterpart to ``--run``: the
  same bulk examination, but bounded by a dollar cap so it can run without an
  operator watching it spend. It refuses to start under CI (``CI`` set in the
  environment) — CI never passes it — and refuses unless ``--confirm-live``
  is also given, so the spend is always named in the invocation itself.

* ``--redescribe`` (with a required ``--worklist``) re-examines exactly the
  pages the listed cards' existing sidecars describe, with the pinned model,
  bypassing the image-only filter and the already-produced skip. The old pass
  is superseded, not overwritten (see ``vision.redescribe``). It is gated like
  ``--live``: ``--budget-usd``, refused under CI, and without
  ``--confirm-live`` it is a no-spend preflight that reports the card and page
  count and the estimated cost.

Naming more than one of the live paths is ambiguous and refused. Naming none of
them means no API call is made, which is what an unattended caller gets by
default.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pursue_index.cli.vision_live import (
    _check_live_preconditions,
    _print_report,
    _run_bulk,
    _run_live,
    _run_live_smoke,
    _run_redescribe,
)
from pursue_index.cli.worklist import (
    WorklistTrancheError,
    exit_on_tranche_error,
    worklist_card_ids,
)
from pursue_index.config import settings
from pursue_index.config.project_root import resolve_relative_data_root
from pursue_index.scrape import load_manifest
from pursue_index.vision.eligibility import EligibleItem, select_eligible
from pursue_index.vision.run import preflight_coverage

vision_app = typer.Typer(name="vision", help="Vision observations for image content.")

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_WORKLIST = typer.Option(
    None, "--worklist", exists=True, dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "cover the full manifest (the escape hatch).",
)
_OBSERVATIONS_SUBPATH = Path("web") / "src" / "data" / "image-observations"


def default_observations_dir() -> Path:
    """The sidecar directory, anchored to the checkout it belongs to.

    The sidecars are committed inside the checkout, so this answer has to be
    the same wherever the CLI is invoked from: a run started in a subdirectory
    must see the sidecars a run started at the root sees. Resolution uses the
    same anchor the data root uses (``config.project_root``) — the project
    sentinel beside this package, identity-checked — and falls back to the
    working directory when the package is installed rather than checked out,
    which is the same answer a relative default has always given there.
    """
    import pursue_index

    return resolve_relative_data_root(
        _OBSERVATIONS_SUBPATH,
        package_dir=Path(pursue_index.__file__).parent,
        cwd=Path.cwd(),
    )


_OPT_OUT = typer.Option(
    None, "--out",
    help="Directory of per-card observation sidecars (<card_id>.json). "
    "Defaults to the checkout's image-observations directory.",
)
_OPT_LIVE_SMOKE = typer.Option(
    None, "--live-smoke",
    help="A LIVE PATH. Examine exactly one card_id via the vision model and "
    "write its sidecar — a single-image smoke test. CI never passes this.",
)
_OPT_RUN = typer.Option(
    False, "--run",
    help="A LIVE PATH. Operator-attended bulk pass: examine every eligible item "
    "in the worklist and write its observations. Omit to preview coverage only.",
)
_OPT_LIVE = typer.Option(
    False, "--live",
    help="A LIVE PATH. Unattended bulk pass under --budget-usd: examine "
    "eligible items until the worklist is covered or the next call would "
    "exceed the budget. Refused under CI, and refused unless --confirm-live "
    "is also given.",
)
_OPT_REDESCRIBE = typer.Option(
    False, "--redescribe",
    help="A LIVE PATH. Re-examine exactly the pages the --worklist cards' "
    "existing sidecars describe with the pinned model, superseding (not "
    "overwriting) the old pass. Needs --worklist, --budget-usd and "
    "--confirm-live; refused under CI. Without --confirm-live it is a "
    "no-spend preflight.",
)
_OPT_CONFIRM_LIVE = typer.Option(
    False, "--confirm-live",
    help="Required with --live and --redescribe: the explicit statement that this invocation "
    "means to spend, so a stray or scheduled command line cannot.",
)
_OPT_OVERRIDE_EXCEPTION = typer.Option(
    False, "--override-method-exception",
    help="With --redescribe: also re-describe cards listed in "
    "data/vision-method-exceptions.json (curated passes). Needs --reason.",
)
_OPT_REASON = typer.Option(
    None, "--reason",
    help="Why a method exception is being overridden. Only valid with "
    "--override-method-exception.",
)
_OPT_BUDGET = typer.Option(
    None, "--budget-usd",
    help="Hard cost cap for --live. Required with --live. Spend is metered "
    "from each response's reported usage at the model's rates, and the run "
    "stops before any call whose worst case would not fit in what is left.",
)


@vision_app.command("run")
def vision_run(
    manifest: Path = _OPT_MANIFEST,
    worklist: Path = _OPT_WORKLIST,
    out: Path = _OPT_OUT,
    live_smoke: str = _OPT_LIVE_SMOKE,
    run: bool = _OPT_RUN,
    live: bool = _OPT_LIVE,
    budget_usd: float = _OPT_BUDGET,
    confirm_live: bool = _OPT_CONFIRM_LIVE,
    redescribe: bool = _OPT_REDESCRIBE,
    override_method_exception: bool = _OPT_OVERRIDE_EXCEPTION,
    reason: str = _OPT_REASON,
) -> None:
    """Preview coverage by default; examine images only with --run, --live-smoke,
    or --live.

    Default: no spend — reports eligible-vs-produced and exits non-zero on a
    shortfall so a release gate can block on uncovered image content.
    """
    _check_live_preconditions(
        run, live_smoke, live, budget_usd, confirm_live, redescribe, worklist
    )
    m, ids = _load_scope(manifest, worklist)
    out = out or default_observations_dir()
    if redescribe:
        return _run_redescribe(m, ids or set(), out, budget_usd, confirm_live,
                               (override_method_exception, reason))
    items = select_eligible(m, ids, settings.ocr_dir)
    if live_smoke:
        return _run_live_smoke(items, out, live_smoke)
    if run:
        return _run_bulk(items, out)
    if live:
        return _run_live(items, out, budget_usd)
    _preview(items, out)


def _load_scope(manifest: Path, worklist: Path | None):
    """The manifest and the worklist's card ids, exiting on a stale worklist."""
    m = load_manifest(manifest)
    try:
        return m, worklist_card_ids(worklist, promoted_sha=m.csv_sha256)
    except WorklistTrancheError as exc:
        exit_on_tranche_error(exc)


def _preview(items: list[EligibleItem], out: Path) -> None:
    """The default no-spend coverage preview; non-zero exit on a shortfall."""
    report = preflight_coverage(items, out)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
