"""Embed pipeline: OCR pages → content-addressed vector file.

Reads every ``pages.jsonl`` whose card has a successful ``meta.json``,
batches the texts through a configurable embedder, and writes
``{out_root}/{model_id}/vectors.bin`` (contiguous float32 [N, D] little
endian) plus ``index.json`` (per-row card_id/page/text_sha/offset).

Idempotent: a row keyed by ``(card_id, page, model_id, text_sha)`` is
only embedded once across runs; an unchanged corpus is a no-op.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pursue_index import get_logger
from pursue_index.embed.store import (
    EmbedSummary,
    IndexRow,
    PageRow,
    iter_card_pages,
    load_existing_augmented_by,
    load_existing_index,
    load_prior_index_rows,
    vectors_to_bytes,
    write_index,
)
from pursue_index.embed.voyage import EmbedResult

log = get_logger(__name__)

DEFAULT_BATCH_SIZE = 64
# Voyage-3 sized at ~500 tokens/page average. Default cap pegged to the
# embed-stage plan's $1 per-invocation guardrail (override via flag).
DEFAULT_COST_CAP_USD = 1.0


class Embedder(Protocol):
    """Minimal contract any embedding adapter must satisfy.

    ``usd_per_million_tokens`` lets each adapter own the rate the pipeline
    uses for cost-cap math — Voyage and OpenAI charge different rates and
    silently using one for the other understates cost by ~2×.
    """

    model: str
    usd_per_million_tokens: float

    def embed_texts(
        self, texts: list[str], input_type: str = "document"
    ) -> EmbedResult: ...


def _batched(rows: list[PageRow], size: int) -> list[list[PageRow]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def _estimate_cost_usd(rows: list[PageRow], usd_per_million_tokens: float) -> float:
    """Rough token count = chars / 4. Voyage docs cite this as a fine prior."""
    total_chars = sum(len(r.text) for r in rows)
    est_tokens = total_chars / 4.0
    return (est_tokens / 1_000_000.0) * usd_per_million_tokens


def _check_cost_cap(
    rows: list[PageRow], cost_cap_usd: float, usd_per_million_tokens: float
) -> float:
    est = _estimate_cost_usd(rows, usd_per_million_tokens)
    if est > cost_cap_usd:
        raise RuntimeError(
            f"Embed run aborted: estimated cost ${est:.2f} exceeds cap "
            f"${cost_cap_usd:.2f}. Re-run with --cost-cap-usd to override."
        )
    return est


def _embed_new_rows(
    new_rows: list[PageRow],
    embedder: Embedder,
    batch_size: int,
    starting_offset: int,
    starting_dim: int,
    summary: EmbedSummary,
    augment_lookup: dict[tuple[str, int], list[str]] | None = None,
) -> tuple[bytes, list[IndexRow], int]:
    """Run new_rows through the embedder; return (bytes, index_rows, dim).

    ``augment_lookup`` is consulted only to decide which new rows get
    their ``augmented=True`` flag flipped — a row is augmented iff its
    ``(card_id, page)`` was in the lookup, meaning the IMAGE-DESCRIPTIONS
    block actually changed the hashed text.
    """
    new_index_rows: list[IndexRow] = []
    accumulated = bytearray()
    dim = starting_dim
    for batch in _batched(new_rows, batch_size):
        result = embedder.embed_texts([r.text for r in batch])
        if not result.vectors:
            continue
        if dim == 0:
            dim = len(result.vectors[0])
        chunk = vectors_to_bytes(result.vectors)
        for i, page_row in enumerate(batch):
            offset = starting_offset + len(accumulated) + i * dim * 4
            is_augmented = (
                augment_lookup is not None
                and (page_row.card_id, page_row.page) in augment_lookup
            )
            new_index_rows.append(
                IndexRow(
                    card_id=page_row.card_id,
                    page=page_row.page,
                    text_sha=page_row.text_sha,
                    offset=offset,
                    augmented=is_augmented,
                )
            )
        accumulated.extend(chunk)
        summary.total_tokens += result.total_tokens
    return bytes(accumulated), new_index_rows, dim


def _select_new_rows(
    ocr_dir: Path,
    index_path: Path,
    limit: int | None,
    augment_lookup: dict[tuple[str, int], list[str]] | None = None,
) -> tuple[list[PageRow], list[PageRow], int]:
    """Walk OCR output and partition into (new, all, prior_dim)."""
    all_rows = iter_card_pages(ocr_dir, augment_lookup=augment_lookup)
    seen, prior_dim = load_existing_index(index_path)
    new_rows = [r for r in all_rows if (r.card_id, r.page, r.text_sha) not in seen]
    if limit is not None:
        new_rows = new_rows[:limit]
    return new_rows, all_rows, prior_dim


def _persist(
    vectors_path: Path,
    index_path: Path,
    model_id: str,
    dim: int,
    new_bytes: bytes,
    new_index_rows: list[IndexRow],
    augmented_by: dict[str, str] | None = None,
) -> list[IndexRow]:
    """Append ``new_bytes`` to vectors, then rewrite ``index.json``.

    Two invariants beyond the obvious append:

    * **Codex P1 — orphan-row drop.** When ``new_index_rows`` includes
      augmented siblings, the un-augmented prior row for the same
      ``(card_id, page)`` is dropped from the index. Without this, the
      embed root keeps both copies and retrieval over the embed root sees
      duplicate vectors per page (the deploy-side dedupe in
      ``build_embed_data.py`` only fires at publish time).
    * **Codex P2 — preserve provenance across runs.** A subsequent
      ``pursue embed run`` without ``--augment-from`` would otherwise
      silently strip ``augmented_by`` even when prior rows are still
      augmented. We default to the prior index's ``augmented_by`` unless
      the current invocation explicitly passes a new one.

    The vector bytes for dropped rows remain on disk (they're already
    appended at this point); only the index reference is removed.
    Compaction is a separate concern.
    """
    with vectors_path.open("ab") as fh:
        fh.write(new_bytes)

    prior_rows = load_prior_index_rows(index_path)
    augmented_keys = {
        (r.card_id, r.page) for r in new_index_rows if r.augmented
    }
    if augmented_keys:
        prior_rows = [
            r for r in prior_rows if (r.card_id, r.page) not in augmented_keys
        ]
    all_index_rows = prior_rows + new_index_rows

    if augmented_by is None:
        augmented_by = load_existing_augmented_by(index_path)

    write_index(index_path, model_id, dim, all_index_rows, augmented_by=augmented_by)
    return all_index_rows


def _resolve_rate(embedder: Embedder, override: float | None) -> float:
    """Pick the $/Mtok rate: explicit override wins, else adapter default."""
    return override if override is not None else embedder.usd_per_million_tokens


def _check_and_log_start(
    new_rows: list[PageRow],
    skipped: int,
    cost_cap_usd: float,
    rate: float,
    model_id: str,
) -> None:
    """Trip the cost cap and emit ``embed.run.start`` so spend is observable."""
    est = _check_cost_cap(new_rows, cost_cap_usd, rate)
    log.info(
        "embed.run.start",
        new_pages=len(new_rows),
        skipped=skipped,
        est_cost_usd=round(est, 4),
        usd_per_million_tokens=rate,
        model=model_id,
    )


def _handle_noop(
    index_path: Path,
    model_id: str,
    prior_dim: int,
    skipped: int,
    augmented_by: dict[str, str] | None,
) -> None:
    """No new rows path: ensure an index.json exists, log, return."""
    if not index_path.exists():
        write_index(
            index_path, model_id, prior_dim, [], augmented_by=augmented_by
        )
    log.info("embed.run.noop", skipped=skipped, model=model_id)


def _prepare_paths(out_root: Path, model_id: str) -> tuple[Path, Path]:
    """Ensure ``{out_root}/{model_id}/`` exists; return (vectors, index) paths."""
    out_dir = out_root / model_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "vectors.bin", out_dir / "index.json"


def embed_run(
    ocr_dir: Path,
    out_root: Path,
    embedder: Embedder,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    cost_cap_usd: float = DEFAULT_COST_CAP_USD,
    usd_per_million_tokens: float | None = None,
    augment_lookup: dict[tuple[str, int], list[str]] | None = None,
    augmented_by: dict[str, str] | None = None,
) -> EmbedSummary:
    """Walk OCR output, embed new pages, append to vectors.bin + index.json.

    ``augment_lookup`` injects alex-zhang42 image tags before text_sha
    (see ``atlas_join.load_atlas_index``); ``augmented_by`` records the
    dataset/revision provenance into index.json. ``usd_per_million_tokens``
    overrides the adapter's published rate for cost-cap math.
    """
    model_id = embedder.model
    vectors_path, index_path = _prepare_paths(out_root, model_id)
    new_rows, all_rows, prior_dim = _select_new_rows(
        ocr_dir, index_path, limit, augment_lookup=augment_lookup
    )
    skipped = len(all_rows) - len(new_rows)
    summary = EmbedSummary(
        skipped=skipped, cards_seen=len({r.card_id for r in all_rows})
    )
    if not new_rows:
        _handle_noop(index_path, model_id, prior_dim, skipped, augmented_by)
        return summary

    rate = _resolve_rate(embedder, usd_per_million_tokens)
    _check_and_log_start(new_rows, skipped, cost_cap_usd, rate, model_id)
    next_offset = vectors_path.stat().st_size if vectors_path.exists() else 0
    new_bytes, new_index_rows, dim = _embed_new_rows(
        new_rows, embedder, batch_size, next_offset, prior_dim, summary,
        augment_lookup=augment_lookup,
    )
    _persist(
        vectors_path, index_path, model_id, dim, new_bytes, new_index_rows,
        augmented_by=augmented_by,
    )
    summary.embedded = len(new_index_rows)
    log.info("embed.run.done", embedded=summary.embedded, model=model_id)
    return summary
