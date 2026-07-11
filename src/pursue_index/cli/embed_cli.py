"""``pursue embed`` sub-command surface.

Split out of ``commands.py`` so the embed CLI's option list doesn't push the
parent module past the file/function size budget. Imports are lazy so the SDKs
only load when the command actually runs.

The external alex-zhang42 VLM augment corpus this command once consumed via
``--augment-from`` was retired 2026-07-11; image-only pages now draw our own
operator-reviewed vision-pass text from the image-observations sidecars (see
``embed.image_observations``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from pursue_index.cli.worklist import worklist_card_ids
from pursue_index.config import settings

embed_app = typer.Typer(name="embed", help="Embed OCR pages into a vector index.")
console = Console()


def _make_embedder(provider: str, model: str) -> Any:
    """Resolve provider name -> embedder instance. Lazy-imports adapters."""
    import os

    if provider == "voyage":
        api_key = os.environ.get("VOYAGE_API_KEY", "")
        if not api_key:
            console.print(
                "[red]error:[/red] VOYAGE_API_KEY is not set; "
                "export it or pass --provider openai once that adapter ships."
            )
            raise typer.Exit(code=2)
        from pursue_index.embed import voyage as voyage_mod

        return voyage_mod.VoyageAdapter(api_key=api_key, model=model)
    if provider == "openai":
        from pursue_index.embed.openai import OpenAIAdapter

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            console.print(
                "[red]error:[/red] OPENAI_API_KEY is not set; "
                "export it or pass --provider voyage."
            )
            raise typer.Exit(code=2)
        return OpenAIAdapter(api_key=api_key, model=model)
    console.print(f"[red]error:[/red] unknown provider: {provider!r}")
    raise typer.Exit(code=2)


# Typer Options declared at module scope so the command function stays short.
# Each Option's help string is the user-facing surface; the rest is plumbing.
_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_PROVIDER = typer.Option(None, "--provider", help="voyage|openai")
_OPT_MODEL = typer.Option(None, "--model", help="Embedding model id")
_OPT_LIMIT = typer.Option(None, "--limit", help="Embed at most N new pages")
_OPT_WORKLIST = typer.Option(
    None,
    "--worklist",
    exists=True,
    dir_okay=False,
    help="Scope the run to the card_ids in this file (one per line). Omit to "
    "embed the whole OCR dir (the escape hatch). Written by `ingest run --from-diff`.",
)
_OPT_COST_CAP = typer.Option(1.0, "--cost-cap-usd", help="Abort if est cost > cap")
_OPT_RATE = typer.Option(None, "--usd-per-million-tokens", help="Override $/Mtok")
_OPT_BATCH = typer.Option(64, "--batch-size", help="Texts per provider call")
_OPT_IMAGE_OBS_INDEX = typer.Option(
    Path("web/src/data/image-observations/index.json"),
    "--image-observations-index",
    exists=False, dir_okay=False,
    help="Path to image-observations index JSON. Genuinely image-only pages "
    "(zero base OCR) whose card_id is listed there receive our own "
    "operator-reviewed vision-pass description as their embedded text, instead "
    "of being dropped. Pass a non-existent path to disable.",
)


def _load_observation_lookup(
    index_path: Path | None,
) -> dict[tuple[str, int], str] | None:
    """Build the image-only vision-text lookup from the observations index.

    Returns ``None`` when the index path is absent or missing, so the embed
    pipeline behaves exactly as before for corpora with no image-observations.
    Otherwise returns ``{(card_id, page): our vision-pass text}`` — consumed by
    the pipeline to give genuinely image-only pages searchable content instead
    of dropping them (see ``embed.image_observations``).
    """
    if index_path is None or not index_path.exists():
        return None
    from pursue_index.embed.image_observations import load_observation_text

    lookup = load_observation_text(index_path)
    if lookup:
        console.print(
            f"[cyan]image-observations:[/cyan] {len(lookup)} image-only pages "
            f"carry our own vision-pass text"
        )
    return lookup or None


def _print_summary(summary: Any) -> None:
    console.print(
        f"[green]✔[/green] embed: {summary.embedded} embedded, "
        f"{summary.skipped} skipped, {summary.total_tokens} tokens, "
        f"{summary.cards_seen} cards"
    )


@embed_app.command("run")
def embed_run_cmd(
    manifest: Path = _OPT_MANIFEST,
    provider: str = _OPT_PROVIDER,
    model: str = _OPT_MODEL,
    limit: int = _OPT_LIMIT,
    cost_cap_usd: float = _OPT_COST_CAP,
    usd_per_million_tokens: float = _OPT_RATE,
    batch_size: int = _OPT_BATCH,
    image_observations_index: Path = _OPT_IMAGE_OBS_INDEX,
    worklist: Path = _OPT_WORKLIST,
) -> None:
    """Embed every OCR'd page that doesn't already have a current vector.

    ``--manifest`` is accepted for pipeline compatibility but no longer read:
    the retired alex-zhang42 augment join was the only consumer of it.
    """
    from pursue_index.embed import pipeline as embed_pipeline  # lazy

    settings.ensure_dirs()
    embedder = _make_embedder(
        provider or settings.embed_provider, model or settings.embed_model
    )
    obs_lookup = _load_observation_lookup(image_observations_index)
    summary = embed_pipeline.embed_run(
        ocr_dir=settings.ocr_dir,
        out_root=settings.embeddings_dir,
        embedder=embedder,
        batch_size=batch_size,
        limit=limit,
        cost_cap_usd=cost_cap_usd,
        usd_per_million_tokens=usd_per_million_tokens,
        only_cards=worklist_card_ids(worklist),
        obs_lookup=obs_lookup,
    )
    _print_summary(summary)
