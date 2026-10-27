"""Assemble one tranche-ready record from what the poll job already computed.

Inputs are plain data: both manifests, the tranche diff (as
``scripts/tranche_diff.py`` commits it), the candidates
(``candidates.build_candidate``), the page counter's counts and fallbacks,
the old-side fetch outcomes and the judge rate. No I/O.

``status`` follows the hand-off spec: ``stop-and-ask`` when any candidate
has a null verdict or ``stop_and_ask`` set, or the page count is partial;
``stop_reasons`` then names each cause. Otherwise ``ready``. ``superseded``
is never produced here -- a record is append-only, so a later sha lists this
one in its own ``supersedes`` instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pursue_index.release.rates import JudgeRate
from pursue_index.tranche_ready.estimate import estimate_block
from pursue_index.tranche_ready.scope import pages_block, scope_cards
from pursue_index.tranche_resave import RESAVE_BUCKET

__all__ = ["SCHEMA_VERSION", "RecordInputs", "build_record"]

SCHEMA_VERSION = "1.0.0"
_DIFF_KEYS = ("renames_confirmed", "new_content", "quarantined", "removed",
              "field_only_changes", "row_changes", "restored_unchanged",
              "restored_modified", "restored_unknown")


@dataclass(frozen=True)
class RecordInputs:
    """Everything one record is built from."""

    old_manifest: dict[str, Any]
    new_manifest: dict[str, Any]
    diff: dict[str, Any]
    candidates: list[dict[str, Any]]
    page_counts: Mapping[str, int]
    new_fallback_ids: Sequence[str]
    old_fetched: int
    old_failures: Sequence[tuple[str, str]]  # (old card_id, failure reason)
    judge: JudgeRate | None
    tranche_issue: int | None
    supersedes: list[dict[str, Any]]
    generated_by: dict[str, Any]
    generated_at: str
    detected_at: str | None = None


def _diff_counts(summary: Mapping[str, int]) -> dict[str, int]:
    """The receipt's summary; the schema has no re-save bucket, so opted-in
    metadata-only re-saves (renames the approval accepts) count as renames."""
    out = {k: int(summary.get(k, 0)) for k in _DIFF_KEYS}
    out["renames_confirmed"] += int(summary.get(RESAVE_BUCKET, 0))
    return out


def _fetch_block(inp: RecordInputs) -> dict[str, Any]:
    failures = [{"card_id": c, "side": "new", "reason": "new_fetch_failed"}
                for c in inp.new_fallback_ids]
    failures += [{"card_id": c, "side": "old", "reason": r} for c, r in inp.old_failures]
    return {"new_fetched": len(inp.page_counts), "new_failed": len(inp.new_fallback_ids),
            "old_fetched": inp.old_fetched, "old_failed": len(inp.old_failures),
            "failures": failures}


def _stop_reasons(candidates: list[dict[str, Any]], fallback: list[str]) -> list[str]:
    reasons = []
    for c in candidates:
        if c["byte_verdict"] is None:
            reasons.append(f"{c['new_card_id']}: no byte verdict ({c['byte_verdict_reason']})")
        elif c["stop_and_ask"]:
            reasons.append(f"{c['new_card_id']}: {c['kind']} bytes are {c['byte_verdict']}")
    if fallback:
        reasons.append(f"estimate partial: {len(fallback)} scoped card(s) priced per card "
                       "(page count unavailable)")
    return reasons


def build_record(inp: RecordInputs) -> dict[str, Any]:
    """The record, in the schema's field order."""
    sha = inp.new_manifest["csv_sha256"]
    scoped = scope_cards(inp.diff, sha, inp.new_manifest, inp.candidates)
    pages, fallback = pages_block(scoped, inp.page_counts)
    reasons = _stop_reasons(inp.candidates, fallback)
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tranche_sha256": sha,
        "tranche_sha12": sha[:12],
        "detected_at": inp.detected_at or inp.generated_at,
        "generated_at": inp.generated_at,
        "status": "stop-and-ask" if reasons else "ready",
        **({"stop_reasons": reasons} if reasons else {}),
        "tranche_issue": inp.tranche_issue,
        "supersedes": list(inp.supersedes),
        "manifest": {
            "old_row_count": len(inp.old_manifest.get("cards", [])),
            "new_row_count": len(inp.new_manifest.get("cards", [])),
            "prior_manifest_sha256": inp.old_manifest.get("csv_sha256"),
            "new_snapshot_sha256": sha,
        },
        "diff": _diff_counts(inp.diff.get("summary", {})),
        "candidates": list(inp.candidates),
        "scope": {"card_count": len(scoped), "cards": scoped},
        "pages": pages,
        "estimate": estimate_block(pages["total"], fallback, inp.judge),
        "fetch": _fetch_block(inp),
        "generated_by": dict(inp.generated_by),
    }
    return record
