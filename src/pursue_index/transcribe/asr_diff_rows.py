"""AUD row logic shared by the ``asr-diff run`` preview and the ``asr-diff live`` plan.

Both commands walk the same rows and must agree on them, so the card
selection, the row duration and the "already compared" check live here once:
the preview's pending/compared/skipped split is the live plan's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pursue_index.card_id import require_card_ids
from pursue_index.scrape import load_manifest
from pursue_index.transcribe import asr_diff_sidecar as sidecar


def aud_card_ids(manifest_path: Path, cards_filter: str | None) -> list[str]:
    """The manifest's AUD card_ids, once each in manifest order, narrowed to
    the comma-separated ``cards_filter`` when given. A malformed card_id in
    the filter raises ``InvalidCardIdError``."""
    wanted = (
        set(require_card_ids(c.strip() for c in cards_filter.split(",") if c.strip()))
        if cards_filter else None
    )
    aud_cards = list(dict.fromkeys(
        c.card_id for c in load_manifest(manifest_path).cards if c.asset_type == "AUD"))
    if wanted is not None:
        aud_cards = [c for c in aud_cards if c in wanted]
    return aud_cards


def row_duration(meta: dict, row: dict) -> float:
    """A row's audio seconds: its own ``audio_duration_s``, else the top-level
    ``meta.audio_duration_s`` for single-row meta only (older single-row meta
    keeps it there; a multi-row card's total is not any one row's). Missing,
    unreadable or negative reads as 0."""
    value = row.get("audio_duration_s")
    if value is None and len(meta.get("rows") or []) <= 1:
        value = meta.get("audio_duration_s")
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class RowState:
    """One transcript row and whether a second-engine pass would compare it."""

    row_key: str
    state: str  # "pending" | "compared" | "skipped"
    duration_s: float
    engine_a: str = ""
    reason: str = ""


def card_row_states(card_dir: Path, engine_b: str) -> list[RowState]:
    """Every row of the card in ``card_dir``, labelled for ``engine_b``.

    ``skipped``: no completed transcript, or a multi-row card (its pages are
    not separable per row). ``compared``: the sidecar already holds a
    comparison under this engine pair of the current transcript version and
    pages. ``pending``: anything else."""
    meta = sidecar.read_meta(card_dir)
    if not meta or meta.get("status") != "ok":
        return [RowState("", "skipped", 0.0, reason="no completed transcript")]
    rows = meta.get("rows") or [{"row_key": ""}]
    if len(rows) > 1:
        return [RowState(str(r.get("row_key", "") or ""), "skipped", row_duration(meta, r),
                         reason="multi-row card: pages are not separable per row") for r in rows]
    row = rows[0]
    row_key = str(row.get("row_key", "") or "")
    engine_a = str(meta.get("engine", ""))
    prior = sidecar.load_existing(card_dir / sidecar.SIDECAR_FILE).get(row_key)
    current = prior and sidecar.should_skip(
        prior, engine_a=engine_a, engine_b=engine_b,
        transcript_version=sidecar.transcript_version(card_dir),
        pages_digest=sidecar.card_pages_digest(card_dir),
    )
    return [RowState(row_key, "compared" if current else "pending", row_duration(meta, row), engine_a)]
