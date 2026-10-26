"""Turnkey ship-tranche release helpers — pure logic (no I/O, no network).

Encodes the operated OCR methodology as a hard verify-before-spend preflight,
a rough cost estimate, and the credential-free "tranche ready" surface that the
poll alert appends to the tranche-detected issue. Keeping this pure means the
poll workflow's credential-isolated `snapshot` job can build the surface without
touching any spend credential.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pursue_index.release import rates
from pursue_index.release.estimate_text import estimate_lines, renderable_ids

# --- operated OCR methodology (single source of truth for the gate) ---
OCR_ENGINE_OF_RECORD = "llm-dots"  # Sonnet 4.6 per page + local dots on a content-filter 400
OCR_ENGINES_ACCEPTED = ("llm-dots", "llm")  # tesseract / surya / auto are retired
OCR_CONCURRENCY_OF_RECORD = 8  # NOT the download concurrency (4)

# --- the operated stage sequence (the contract an operator follows) ---
# Every tranche runs these stages, in this order. `vision` sits with the other
# operator-attended spend stages: it reads page images, so it follows OCR, and
# the embed payload carries its observations alongside page text, so it
# precedes embed. Stages are named here once and rendered from here, so the
# published contract and this constant cannot describe different releases.
OPERATED_STAGE_SEQUENCE = (
    "approve",
    f"OCR `--engine {OCR_ENGINE_OF_RECORD} "
    f"--concurrency {OCR_CONCURRENCY_OF_RECORD} --force`",
    "vision",
    "curate clean-qc",
    "embed",
    "ship-ready",
)



@dataclass
class PreflightResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def preflight_ocr(
    *, engine: str | None, concurrency: int | None, anthropic_key_present: bool
) -> PreflightResult:
    """Refuse to spend on OCR unless the operated methodology is satisfied.

    The Release-4 fumble is exactly what this blocks: a stale env resolved the
    engine to tesseract-primary and the download concurrency (4) was mistaken
    for the OCR value. Any of those now hard-fails before a dollar is spent.
    """
    errors: list[str] = []
    if engine not in OCR_ENGINES_ACCEPTED:
        errors.append(
            f"OCR engine {engine!r} is not operated — use {OCR_ENGINE_OF_RECORD!r} "
            f"(accepted: {', '.join(OCR_ENGINES_ACCEPTED)}). tesseract/surya/auto are "
            f"retired; refusing to spend."
        )
    if concurrency is None or concurrency < OCR_CONCURRENCY_OF_RECORD:
        errors.append(
            f"OCR concurrency {concurrency!r} < operated {OCR_CONCURRENCY_OF_RECORD}. "
            f"The download concurrency (4) is NOT the OCR value."
        )
    if not anthropic_key_present:
        errors.append("ANTHROPIC_API_KEY not resolved — OCR would fail; refusing to spend.")
    return PreflightResult(ok=not errors, errors=errors)


def estimate_cost_usd(*, cards: int | None = None, pages: int | None = None) -> float:
    """Low-rate $ estimate across every spend stage, priced by ``rates``.

    Prefer ``pages``; otherwise ``cards`` are priced with the per-card
    fallback (``rates.AVG_PAGES_PER_CARD`` pages each).
    """
    if pages is None:
        pages = (cards or 0) * rates.AVG_PAGES_PER_CARD
    return round(rates.cost_band(pages).low, 2)


_WORKLIST_PREVIEW_CAP = 15  # cap the inline card-id list so a big tranche stays readable


def _worklist_lines(scoped_ids: list[str] | None) -> list[str]:
    """A capped, credential-free preview of the scoped card_ids (the worklist)."""
    if not scoped_ids:
        return []
    named = renderable_ids(scoped_ids)
    shown = named[:_WORKLIST_PREVIEW_CAP]
    out = ["", "<details><summary>scoped card_ids</summary>", ""]
    out += [f"* `{cid}`" for cid in shown]
    remainder = len(scoped_ids) - len(shown)
    if remainder > 0:
        out.append(f"* … and {remainder} more")
    out.append("</details>")
    return out


def _with_uncounted(
    n: int,
    scoped_ids: list[str] | None,
    page_counts: Mapping[str, int],
    fallback_card_ids: Sequence[str],
    av_card_ids: Sequence[str] = (),
) -> list[str]:
    out = list(fallback_card_ids)
    known = set(page_counts) | set(out) | set(av_card_ids)
    if scoped_ids:
        return out + [c for c in dict.fromkeys(scoped_ids) if c not in known]
    return out + [""] * max(0, n - len(known))


def _estimate(
    n: int,
    scoped_ids: list[str] | None,
    page_counts: Mapping[str, int] | None,
    fallback_card_ids: Sequence[str],
    judge: rates.JudgeRate | None,
    av_card_ids: Sequence[str] = (),
) -> list[str]:
    """The per-page band; any scoped card with no count falls back to the guess.

    The poll fetches only PDFs, but ``ingest`` OCRs every PDF/IMG card, so a
    scoped card that is neither counted nor already a fallback is priced as one.
    """
    if page_counts is None:
        fallback_card_ids = list(scoped_ids or []) or [""] * n
        page_counts = {}
    else:
        fallback_card_ids = _with_uncounted(
            n, scoped_ids, page_counts, fallback_card_ids, av_card_ids
        )
    return estimate_lines(
        pages=sum(page_counts.values()), fallback_card_ids=fallback_card_ids, judge=judge
    )


def build_tranche_ready_summary(
    *,
    tranche: str,
    verdict: str,
    added: int,
    removed: int,
    field_changes: int,
    new_columns: int,
    scoped_count: int,
    scoped_ids: list[str] | None = None,
    page_counts: Mapping[str, int] | None = None,
    fallback_card_ids: Sequence[str] = (),
    judge: rates.JudgeRate | None = None,
    av_card_ids: Sequence[str] = (),
) -> str:
    """Markdown the poll alert appends so the operator sees WHAT to run.

    Credential-free. ``page_counts`` (card_id -> pages, from the poll's PDF
    fetch) and ``fallback_card_ids`` (cards whose fetch failed) price the
    tranche per page with the judge figure labeled by ``judge``; without
    ``page_counts`` every scoped card falls back to the per-card guess and the
    figure is marked partial. ``scoped_count`` is the new-card upper bound,
    exact OCR scope comes from the ``--from-diff --dry-run`` preview. When ``scoped_ids`` is
    given, a capped preview of the actual card_ids (the work-list) is folded in
    so the operator sees which cards, not only how many. ``av_card_ids`` (VID/AUD
    cards, which ``ingest`` fetches but never OCRs) are never priced as OCR pages. Includes a copy-paste
    ``/ship-tranche <sha>`` block.
    """
    n = scoped_count
    lines = [
        f"### Tranche `{tranche[:12]}` — ready to ingest",
        "",
        f"**Verdict:** `{verdict}` · added {added}, removed {removed}, "
        f"field-only {field_changes}, new-columns {new_columns}",
        f"**Scoped work-list:** {n} card(s) to download → OCR → embed",
    ]
    if n == 0:
        lines.append("_(metadata-only tranche — no cards to OCR/embed; promote-only)_")
    else:
        lines += _estimate(n, scoped_ids, page_counts, fallback_card_ids, judge, av_card_ids)
        lines += _worklist_lines(scoped_ids)
    lines += [
        "",
        "**Run the operated release** — drives "
        + " → ".join(OPERATED_STAGE_SEQUENCE)
        + ", with a verify-before-spend engine check:",
        "```",
        f"/ship-tranche {tranche}",
        "```",
        "_`/ship-tranche` is an operator-local driver, not a command published "
        "in this repository. The stage sequence above is the contract — running "
        "those stages explicitly is equivalent._",
    ]
    return "\n".join(lines)
