"""Turnkey ship-tranche release helpers — pure logic (no I/O, no network).

Encodes the operated OCR methodology as a hard verify-before-spend preflight,
a rough cost estimate, and the credential-free "tranche ready" surface that the
poll alert appends to the tranche-detected issue. Keeping this pure means the
poll workflow's credential-isolated `snapshot` job can build the surface without
touching any spend credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- operated OCR methodology (single source of truth for the gate) ---
OCR_ENGINE_OF_RECORD = "llm-dots"  # Sonnet 4.6 per page + local dots on a content-filter 400
OCR_ENGINES_ACCEPTED = ("llm-dots", "llm")  # tesseract / surya / auto are retired
OCR_CONCURRENCY_OF_RECORD = 8  # NOT the download concurrency (4)

# order-of-magnitude per-page costs for the estimate (honest, not billing-exact)
_OCR_USD_PER_PAGE = 0.012      # Sonnet 4.6 vision OCR, avg page
_EMBED_USD_PER_PAGE = 0.00004  # voyage-3
_AVG_PAGES_PER_CARD = 20       # heuristic when only card counts are known (pre-download)


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
    """Rough OCR+embed $ estimate. Prefer ``pages``; fall back to a per-card heuristic."""
    if pages is None:
        pages = (cards or 0) * _AVG_PAGES_PER_CARD
    return round(pages * (_OCR_USD_PER_PAGE + _EMBED_USD_PER_PAGE), 2)


_WORKLIST_PREVIEW_CAP = 15  # cap the inline card-id list so a big tranche stays readable


def _worklist_lines(scoped_ids: list[str] | None) -> list[str]:
    """A capped, credential-free preview of the scoped card_ids (the worklist)."""
    if not scoped_ids:
        return []
    shown = scoped_ids[:_WORKLIST_PREVIEW_CAP]
    out = ["", "<details><summary>scoped card_ids</summary>", ""]
    out += [f"* `{cid}`" for cid in shown]
    remainder = len(scoped_ids) - len(shown)
    if remainder > 0:
        out.append(f"* … and {remainder} more")
    out.append("</details>")
    return out


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
) -> str:
    """Markdown the poll alert appends so the operator sees WHAT to run.

    Credential-free (no page counts pre-download, so the cost is a per-card
    estimate; ``scoped_count`` is the new-card upper bound, exact OCR scope
    comes from the ``--from-diff --dry-run`` preview). When ``scoped_ids`` is
    given, a capped preview of the actual card_ids (the work-list) is folded in
    so the operator sees which cards, not only how many. Includes a copy-paste
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
        lines.append(f"**Est. OCR+embed cost:** ~${estimate_cost_usd(cards=n):.2f} (rough)")
        lines += _worklist_lines(scoped_ids)
    lines += [
        "",
        "**Run the operated release** — drives approve → OCR "
        "`--engine llm-dots --concurrency 8 --force` → curate clean-qc → embed → "
        "ship-ready, with a verify-before-spend engine check:",
        "```",
        f"/ship-tranche {tranche}",
        "```",
        "_`/ship-tranche` is an operator-local driver, not a command published "
        "in this repository. The stage sequence above is the contract — running "
        "those stages explicitly is equivalent._",
    ]
    return "\n".join(lines)
