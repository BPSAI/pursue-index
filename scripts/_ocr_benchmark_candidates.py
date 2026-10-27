"""Candidate registry + pure cost-estimate helpers for the OCR benchmark harness.

Split out of ``run_ocr_benchmark.py`` to keep its function count under the
arch limit. No deps beyond ``dataclasses`` — importable without
pdf2image/pursue_index/anthropic, so the --dry-run path (and its tests)
never need those installed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    """A benchmarkable LLM OCR engine: a model id plus its own pricing."""

    name: str
    model: str
    price_input_per_m: float
    price_output_per_m: float
    price_cache_read_per_m: float


# Anthropic pricing (per million tokens) — claude-haiku-4-5 in 2026-05. This
# is the truth-proxy engine (key "llm" in run_ocr_benchmark.py); its cost
# feeds the median/capped-CER table, not the addendum candidates below.
PRICE_INPUT_PER_M = 1.0
PRICE_OUTPUT_PER_M = 5.0
PRICE_CACHE_READ_PER_M = 0.10  # 10% of input rate

# The default truth-proxy engine, expressed as a Candidate purely so
# --dry-run can report it next to the addendum candidates below.
DEFAULT_CANDIDATE = Candidate(
    "haiku-4-5", "claude-haiku-4-5",
    PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M, PRICE_CACHE_READ_PER_M,
)

# Addendum candidates benchmarked alongside the default truth-proxy engine
# (issue #39). Priced per Anthropic's published per-token rate, same
# sourcing convention as SONNET_46_INPUT_USD_PER_MTOK in
# scripts/_reocr_helpers.py.
ADDENDUM_CANDIDATES: tuple[Candidate, ...] = (
    Candidate("sonnet-5-5", "claude-sonnet-5-5", 2.0, 10.0, 0.20),
)

ALL_CANDIDATES: tuple[Candidate, ...] = (DEFAULT_CANDIDATE, *ADDENDUM_CANDIDATES)

# Per-page token estimate used only for the --dry-run cost projection (no
# real usage data exists before a candidate has ever run). Same basis as
# the pre-usage-tracking estimate scripts/reocr_altered.py used to use (see
# tests/unit/test_ocr_llm.py's note: ~21% under reality, but a reasonable
# order-of-magnitude pre-flight number).
EST_INPUT_TOKENS_PER_PAGE = 1500
EST_OUTPUT_TOKENS_PER_PAGE = 600


def estimate_candidate_cost(candidate: Candidate, pages: int) -> float:
    """Pre-flight cost projection for ``pages`` pages, no API call involved."""
    return pages * (
        EST_INPUT_TOKENS_PER_PAGE / 1_000_000 * candidate.price_input_per_m
        + EST_OUTPUT_TOKENS_PER_PAGE / 1_000_000 * candidate.price_output_per_m
    )


def dry_run_report(golden: list[dict], pages_per_card: int) -> str:
    """Per-candidate cost projection for an addendum run over the v3 set."""
    total_pages = len(golden) * pages_per_card
    lines = [
        f"Dry run — v3 document set: {len(golden)} cards × {pages_per_card} pages "
        f"= {total_pages} pages. No API calls made.",
        "Estimated cost per candidate:",
    ]
    for candidate in ALL_CANDIDATES:
        cost = estimate_candidate_cost(candidate, total_pages)
        lines.append(
            f"  {candidate.name:<12} ({candidate.model}): "
            f"${cost:.4f} total (${cost / total_pages:.4f}/page)"
        )
    return "\n".join(lines)
