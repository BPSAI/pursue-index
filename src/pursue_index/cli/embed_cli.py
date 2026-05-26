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


def _read_sidecar(corpus_path: Path, suffix: str) -> str:
    """Return the trimmed sidecar content for ``<corpus>.{suffix}``.

    Accepts both ``<stem>.{suffix}`` and ``<filename>.{suffix}`` forms.
    Raises ``FileNotFoundError`` when neither is present and ``ValueError``
    on an empty sidecar — both cases are forensic half-truths that the
    plan calls out as non-negotiable.
    """
    candidates = [
        corpus_path.with_suffix(f".{suffix}"),
        corpus_path.parent / (corpus_path.name + f".{suffix}"),
    ]
    for p in candidates:
        if p.exists():
            text = p.read_text().strip()
            if not text:
                raise ValueError(
                    f"augment provenance: {p} is empty; "
                    f"expected the {suffix} value on the first line."
                )
            # ``.sha256`` files are ``<hex>  <filename>``; pick the hex.
            return text.split()[0]
    raise FileNotFoundError(
        f"augment provenance: no .{suffix} sidecar next to {corpus_path}; "
        f"expected one of {[str(c) for c in candidates]}"
    )


def _load_augment_provenance(corpus_path: Path) -> dict[str, str]:
    """Read the dataset/revision/sha256 sidecars next to ``corpus_path``.

    The build script ``scripts/build_alex_zhang_corpus.py`` writes
    ``<stem>.sha256`` and ``<stem>.revision`` next to the corpus file.
    Both sidecars must exist and be non-empty: an ``augmented_by`` block
    written into ``index.json`` is provenance, and provenance with empty
    ``revision`` or ``sha256`` is a forensic half-truth (nayru P1). Fail
    loudly here rather than silently emit one.
    """
    return {
        "dataset": "alex-zhang42/ufo-pursue-open-atlas",
        "revision": _read_sidecar(corpus_path, "revision"),
        "sha256": _read_sidecar(corpus_path, "sha256"),
    }


def _maybe_load_augment(
    augment_from: Path | None,
    manifest: Manifest,
    miss_rate_threshold: float,
) -> tuple[dict[tuple[str, int], list[str]] | None, dict[str, str] | None]:
    """Return ``(lookup, provenance)`` or ``(None, None)`` if not augmenting."""
    if augment_from is None:
        return None, None
    from pursue_index.embed.atlas_join import (
        AtlasJoinError,
        load_atlas_index,
    )

    try:
        lookup = load_atlas_index(
            augment_from, manifest, miss_rate_threshold=miss_rate_threshold
        )
        provenance = _load_augment_provenance(augment_from)
    except (AtlasJoinError, FileNotFoundError, ValueError) as exc:
        console.print(f"[red]error:[/red] augment load failed: {exc}")
        raise typer.Exit(code=2) from exc
    console.print(
        f"[cyan]augment:[/cyan] {len(lookup)} pages have VLM image tags "
        f"from {provenance['dataset']} @ {provenance['revision'][:12]}"
    )
    return lookup, provenance


def _apply_image_observations_quarantine(
    lookup: dict[tuple[str, int], list[str]] | None,
    quarantine_index_path: Path | None,
) -> dict[tuple[str, int], list[str]] | None:
    """Drop augment_lookup entries for card_ids in the image-observations index.

    Cards with operator-verified image observations supersede the alex-
    zhang42 (Zhang) pass for those cards. Per the supersede policy in
    pursue-opsec-staging/findings/2026-05-25-vision-augmentation-and-
    image-observations-architecture.md, Zhang's IMAGE-DESCRIPTIONS block
    must be excluded from chunks for these card_ids before embedding.

    Returns the filtered lookup (or input unchanged when no quarantine
    applies). Idempotent.
    """
    if lookup is None or quarantine_index_path is None:
        return lookup
    if not quarantine_index_path.exists():
        return lookup
    import json

    try:
        idx = json.loads(quarantine_index_path.read_text())
    except json.JSONDecodeError:
        console.print(
            f"[yellow]warn:[/yellow] image-observations index "
            f"{quarantine_index_path} is not valid JSON; ignoring quarantine"
        )
        return lookup
    quarantined = set(idx.get("card_ids", []))
    if not quarantined:
        return lookup
    filtered = {k: v for k, v in lookup.items() if k[0] not in quarantined}
    dropped = len(lookup) - len(filtered)
    console.print(
        f"[cyan]quarantine:[/cyan] {dropped} Zhang augment entries dropped "
        f"({len(quarantined)} card_ids in image-observations index, "
        f"superseded by operator-verified observations)"
    )
    return filtered


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
    min=0.0,
    max=0.5,
    help="Atlas join miss-rate ceiling (default 1%; must be in [0.0, 0.5] — "
    "higher values would silently disable the join quality gate).",
)
_OPT_IMAGE_OBS_INDEX = typer.Option(
    Path("web/src/data/image-observations/index.json"),
    "--image-observations-index",
    exists=False, dir_okay=False,
    help="Path to image-observations index JSON. Card_ids listed there have "
    "operator-verified observations that supersede the augment-from pass; "
    "the embed pipeline excludes Zhang's IMAGE-DESCRIPTIONS for those cards. "
    "Default location is auto-discovered; pass an alternate path or a "
    "non-existent path to disable quarantine.",
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
    image_observations_index: Path = _OPT_IMAGE_OBS_INDEX,
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
    augment_lookup = _apply_image_observations_quarantine(
        augment_lookup, image_observations_index
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
