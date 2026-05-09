"""Novelty compute orchestrator: PURSUE embeddings vs reference index → sidecar.

Reads the PURSUE embed index (the same shape ``pursue embed run`` writes),
loads a reference embed index (a separate corpus run through the same
pipeline), runs cosine top-1 per page, aggregates to card level, and
writes ``data/novelty/latest.json`` for the build helper.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pursue_index import get_logger
from pursue_index.embed.store import load_prior_index_rows
from pursue_index.novelty.aggregate import (
    DEFAULT_THRESHOLDS,
    CardNovelty,
    Thresholds,
    aggregate_card,
)
from pursue_index.novelty.compare import (
    PageMatch,
    ReferenceIndex,
    cosine_top1,
    load_reference_index,
)

log = get_logger(__name__)


@dataclass
class NoveltyReport:
    """Counters returned to the CLI after a compute run."""

    cards_processed: int = 0
    pages_compared: int = 0
    archive_id: str = ""


def _read_pursue_vectors(pursue_embed_dir: Path) -> tuple[list[list[float]], list]:
    """Load the PURSUE embed index — vectors + parallel index rows."""
    rows = load_prior_index_rows(pursue_embed_dir / "index.json")
    if not rows:
        return [], []
    payload = json.loads((pursue_embed_dir / "index.json").read_text())
    n = int(payload["n"])
    dim = int(payload["dim"])
    raw = (pursue_embed_dir / "vectors.bin").read_bytes()
    import struct as _struct

    flat = _struct.unpack(f"<{n * dim}f", raw)
    vectors = [list(flat[i * dim : (i + 1) * dim]) for i in range(n)]
    return vectors, rows


def _match_page(
    vec: list[float], ref: ReferenceIndex, page_num: int
) -> PageMatch | None:
    """Cosine top-1 a single PURSUE page against the loaded reference index."""
    if not ref.vectors:
        return None
    idx, sim = cosine_top1(vec, ref.vectors)
    if idx < 0:
        return None
    row = ref.rows[idx]
    return PageMatch(
        page=page_num,
        ref_card_id=row.card_id,
        ref_page=row.page,
        similarity=round(sim, 4),
        archive_id=ref.archive_id,
    )


def _group_matches_by_card(
    pursue_vectors: list[list[float]],
    pursue_rows: list,
    ref: ReferenceIndex,
) -> dict[str, list[PageMatch]]:
    by_card: dict[str, list[PageMatch]] = defaultdict(list)
    for vec, row in zip(pursue_vectors, pursue_rows, strict=True):
        match = _match_page(vec, ref, row.page)
        if match is not None:
            by_card[row.card_id].append(match)
        else:
            by_card[row.card_id]  # keep card present even with no matches
    return by_card


def _serialize_card(card: CardNovelty) -> dict:
    return {
        "card_id": card.card_id,
        "disclosure_status": card.disclosure_status,
        "novelty_score": card.novelty_score,
        "matches": [
            {
                "page": m.page,
                "ref_archive": m.archive_id,
                "ref_card_id": m.ref_card_id,
                "ref_page": m.ref_page,
                "similarity": m.similarity,
            }
            for m in card.top_matches
        ],
    }


def _write_sidecar(
    out_path: Path,
    archive_id: str,
    thresholds: Thresholds,
    cards: list[CardNovelty],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "archive_id": archive_id,
        "computed_at": datetime.now(UTC).isoformat(),
        "thresholds": {"high": thresholds.high, "partial": thresholds.partial},
        "cards": [_serialize_card(c) for c in cards],
    }
    out_path.write_text(json.dumps(payload, indent=2))


def compute_novelty(
    pursue_embed_dir: Path,
    reference_embed_dir: Path,
    archive_id: str,
    out_path: Path,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> NoveltyReport:
    """Run the cosine top-1 + aggregation pipeline; write the sidecar JSON.

    ``pursue_embed_dir`` and ``reference_embed_dir`` are both the per-model
    directories the embed pipeline writes (e.g. ``.../voyage-3/``).
    """
    ref = load_reference_index(reference_embed_dir, archive_id=archive_id)
    pursue_vectors, pursue_rows = _read_pursue_vectors(pursue_embed_dir)

    by_card = _group_matches_by_card(pursue_vectors, pursue_rows, ref)
    cards = [aggregate_card(cid, by_card[cid], thresholds) for cid in by_card]

    _write_sidecar(out_path, archive_id, thresholds, cards)
    log.info(
        "novelty.compute.done",
        archive=archive_id,
        cards=len(cards),
        pages=len(pursue_rows),
    )
    return NoveltyReport(
        cards_processed=len(cards),
        pages_compared=len(pursue_rows),
        archive_id=archive_id,
    )
