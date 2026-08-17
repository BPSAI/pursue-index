"""``pursue av-fetch run`` — the A/V direct-fetch stage (pipeline stage 3).

Automates the operator's manual DVIDS download: resolve each in-scope VID/AUD
card's DOD asset file URL and retrieve it, through the same HTTP client every
other public fetch in this project uses. Output lands in ``--staging-dir``
named ``DOD_<id>.mp4`` — the exact filename convention
``scripts/ingest_release_videos.py --desktop`` already consumes, unchanged.

Split out of ``commands.py`` (same rationale as ``vision_cli``/``embed_cli``)
to keep that module slim.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pursue_index.av_fetch.fetch import AVFetchReport, fetch_worklist
from pursue_index.av_fetch.select import DVIDS_ASSET_TYPES, select_av_rows
from pursue_index.config import settings
from pursue_index.scrape import load_manifest

av_fetch_app = typer.Typer(
    name="av-fetch", help="Direct-fetch DVIDS-hosted A/V bytes (VID/AUD)."
)
console = Console()

_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_RELEASE_DATE = typer.Option(
    ..., "--release-date",
    help="Manifest release_date to fetch (matches ingest_release_videos.py).",
)
_OPT_STAGING_DIR = typer.Option(
    None, "--staging-dir",
    help="Where DOD_<id>.mp4 files land (default: <data_root>/av-fetch).",
)
_OPT_ASSET_TYPES = typer.Option(
    ",".join(DVIDS_ASSET_TYPES), "--asset-types",
    help="Comma-separated asset types to fetch (default VID,AUD).",
)
_OPT_DRY_RUN = typer.Option(
    False, "--dry-run", help="Print the scoped card set; fetch nothing."
)


def _print_report(report: AVFetchReport) -> None:
    console.print(
        f"[cyan]av-fetch:[/cyan] fetched={report.fetched} skipped={report.skipped} "
        f"failed={report.failed} total={len(report.items)}"
    )
    for item in report.items:
        if item.status == "failed":
            console.print(f"  [red]-[/red] {item.card_id} ({item.dvids_video_id}): {item.error}")


@av_fetch_app.command("run")
def av_fetch_run(
    manifest: Path = _OPT_MANIFEST,
    release_date: str = _OPT_RELEASE_DATE,
    staging_dir: Path = _OPT_STAGING_DIR,
    asset_types: str = _OPT_ASSET_TYPES,
    dry_run: bool = _OPT_DRY_RUN,
) -> None:
    """Fetch every in-scope A/V row's bytes, or preview scope with ``--dry-run``.

    Exits non-zero on any per-item fetch failure — a shortfall the operator
    must see, never a silent partial staging directory.
    """
    m = load_manifest(manifest)
    types = tuple(t.strip() for t in asset_types.split(",") if t.strip())
    rows = select_av_rows(m.cards, release_date, types)
    out_dir = staging_dir or (settings.data_root / "av-fetch")

    console.print(f"[cyan]av-fetch:[/cyan] {release_date} A/V rows ({types}): {len(rows)}")
    if dry_run:
        for c in rows:
            console.print(f"  {c.card_id}  dvids={c.dvids_video_id}  type={c.asset_type}")
        return

    report = fetch_worklist(rows, out_dir)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)
