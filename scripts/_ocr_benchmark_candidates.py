"""Candidate registry + pure cost-estimate helpers for the OCR benchmark harness.

Split out of ``run_ocr_benchmark.py`` to keep its function count under the
arch limit. No deps beyond ``dataclasses`` — importable without
pdf2image/pursue_index/anthropic, so the --dry-run path (and its tests)
never need those installed. Pricing lookup, the spend cap and the engine
check live here too, for the same reason.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable
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

# Every model the truth-proxy pass may resolve to (settings.ocr_llm_model,
# which PURSUE_OCR_LLM_MODEL overrides), each with its own price. A model not
# listed here is refused rather than priced at another model's rate.
# claude-sonnet-4-6 is the operated OCR engine's model; its rates match
# SONNET_46_*_USD_PER_MTOK in scripts/_reocr_helpers.py, cache read at 10%.
PRICED_MODELS: tuple[Candidate, ...] = (
    *ALL_CANDIDATES,
    Candidate("sonnet-4-6", "claude-sonnet-4-6", 3.0, 15.0, 0.30),
)

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


class CapReachedError(Exception):
    """The next paid call would take the run past ``--hard-cap-usd``."""


@dataclass
class Budget:
    """Running spend against an optional cap, checked before each paid call.

    Each call is checked against the larger of its estimate and the costliest
    call so far, so a run can pass the cap by at most one call's overrun. The
    caller charges a call that raises too (see ``run_llm``), since it may have
    been billed.
    """

    cap_usd: float | None = None
    spent_usd: float = 0.0
    max_call_usd: float = 0.0

    def reserve(self, next_cost_usd: float) -> None:
        """Refuse the next call if it could take spend past the cap."""
        expected = max(next_cost_usd, self.max_call_usd)
        if self.cap_usd is not None and self.spent_usd + expected > self.cap_usd:
            raise CapReachedError(
                f"stopped on the hard cap: spent ${self.spent_usd:.4f} of "
                f"${self.cap_usd:.4f}, and the next call could cost ${expected:.4f}"
            )

    def add(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        self.max_call_usd = max(self.max_call_usd, cost_usd)


def candidate_for_model(model: str) -> Candidate:
    """The priced candidate for ``model``; a model with no price is refused."""
    for candidate in PRICED_MODELS:
        if candidate.model == model:
            return candidate
    known = ", ".join(c.model for c in PRICED_MODELS)
    raise SystemExit(f"run_ocr_benchmark: no price for model {model!r} (priced: {known}). "
                     "Add it to _ocr_benchmark_candidates.py before running.")


def missing_engines(find_spec: Callable[[str], object] = importlib.util.find_spec,
                    which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """Why each optional OCR engine can't run here; empty when all can."""
    problems = []
    if find_spec("surya") is None:
        problems.append("surya: the surya package is not installed (install the GPU extras)")
    if which("tesseract") is None:
        problems.append("tesseract: the tesseract binary is not on PATH")
    return problems


def engine_lines(truth: Candidate, cap_usd: float | None) -> str:
    """The model id and estimated per-page cost of every LLM engine in the run."""
    lines = [f"  llm ({truth.name}): {truth.model}, "
             f"~${estimate_candidate_cost(truth, 1):.4f}/page"]
    lines += [f"  {c.name}: {c.model}, ~${estimate_candidate_cost(c, 1):.4f}/page"
              for c in ADDENDUM_CANDIDATES]
    lines.append(f"  hard cap: ${cap_usd:.4f}" if cap_usd is not None else "  hard cap: none")
    return "\n".join(lines)
