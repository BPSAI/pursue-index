"""``pursue embed`` sub-command surface.

Split out of ``commands.py`` so the embed CLI's option list (including the
alex-zhang42 augmentation flags) doesn't push the parent module past the
file/function size budget. Imports are lazy so the SDKs only load when the
command actually runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from pursue_index.config import settings
from pursue_index.scrape import Manifest, load_manifest

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


def _load_augment_provenance(corpus_path: Path) -> dict[str, str]:
    """Read the dataset/revision/sha256 sidecars next to ``corpus_path``.

    The build script ``scripts/build_alex_zhang_corpus.py`` writes
    ``<stem>.sha256`` and ``<stem>.revision`` next to the corpus file
    (replacing the ``.jsonl`` suffix). This helper looks for both forms
    so an operator-renamed corpus still resolves cleanly.
    """
    candidates_sha = [
        corpus_path.with_suffix(".sha256"),
        corpus_path.parent / (corpus_path.name + ".sha256"),
    ]
    candidates_rev = [
        corpus_path.with_suffix(".revision"),
        corpus_path.parent / (corpus_path.name + ".revision"),
    ]
    sha = ""
    revision = ""
    for p in candidates_sha:
        if p.exists():
            text = p.read_text().strip()
            sha = text.split()[0] if text else ""
            break
    for p in candidates_rev:
        if p.exists():
            revision = p.read_text().strip()
            break
    return {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": revision,
        "sha256": sha,
    }


def _maybe_load_augment(
    augment_from: Path | None,
    manifest: Manifest,
    miss_rate_threshold: float,
) -> tuple[dict[tuple[str, int], list[str]] | None, dict[str, str] | None]:
    """Return ``(lookup, provenance)`` or ``(None, None)`` if not augmenting."""
    if augment_from is None:
        return None, None
    from pursue_index.embed.atlas_join import load_atlas_index

    lookup = load_atlas_index(
        augment_from, manifest, miss_rate_threshold=miss_rate_threshold
    )
    provenance = _load_augment_provenance(augment_from)
    console.print(
        f"[cyan]augment:[/cyan] {len(lookup)} pages have VLM image tags "
        f"from {provenance['dataset']} @ "
        f"{provenance['revision'][:12] or '?'}"
    )
    return lookup, provenance


# Typer Options declared at module scope so the command function stays short.
# Each Option's help string is the user-facing surface; the rest is plumbing.
_OPT_MANIFEST = typer.Option(..., "--manifest", exists=True, dir_okay=False)
_OPT_PROVIDER = typer.Option(None, "--provider", help="voyage|openai")
_OPT_MODEL = typer.Option(None, "--model", help="Embedding model id")
_OPT_LIMIT = typer.Option(None, "--limit", help="Embed at most N new pages")
_OPT_COST_CAP = typer.Option(1.0, "--cost-cap-usd", help="Abort if est cost > cap")
_OPT_RATE = typer.Option(None, "--usd-per-million-tokens", help="Override $/Mtok")
_OPT_BATCH = typer.Option(64, "--batch-size", help="Texts per provider call")
_OPT_AUGMENT = typer.Option(
    None, "--augment-from", exists=True, dir_okay=False,
    help="alex-zhang42-corpus.jsonl path. Appends [[IMAGE-DESCRIPTIONS via ...]] "
    "to matching pages before hashing. Reads .sha256/.revision sidecars for "
    "index.json augmented_by provenance.",
)
_OPT_MISS_RATE = typer.Option(
    0.01, "--augment-miss-rate-threshold",
    help="Atlas join miss-rate ceiling (default 1%).",
)


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
    augment_from: Path = _OPT_AUGMENT,
    augment_miss_rate_threshold: float = _OPT_MISS_RATE,
) -> None:
    """Embed every OCR'd page that doesn't already have a current vector."""
    from pursue_index.embed import pipeline as embed_pipeline  # lazy

    settings.ensure_dirs()
    m = load_manifest(manifest)
    embedder = _make_embedder(
        provider or settings.embed_provider, model or settings.embed_model
    )
    augment_lookup, augmented_by = _maybe_load_augment(
        augment_from, m, augment_miss_rate_threshold
    )
    summary = embed_pipeline.embed_run(
        ocr_dir=settings.ocr_dir,
        out_root=settings.embeddings_dir,
        embedder=embedder,
        batch_size=batch_size,
        limit=limit,
        cost_cap_usd=cost_cap_usd,
        usd_per_million_tokens=usd_per_million_tokens,
        augment_lookup=augment_lookup,
        augmented_by=augmented_by,
    )
    _print_summary(summary)
