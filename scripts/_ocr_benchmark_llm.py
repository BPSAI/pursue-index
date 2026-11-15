"""The LLM passes of the OCR benchmark: per-page calls, usage capture, pricing.

Split out of ``run_ocr_benchmark.py`` to keep it under the arch limits. Each
page is priced at its candidate's own rates and, with a ``Budget``, refused
before its call when its estimate could take the run past the cap.
"""

from __future__ import annotations

import time
from pathlib import Path

from _ocr_benchmark_candidates import DEFAULT_CANDIDATE, Budget, Candidate, estimate_candidate_cost

from pursue_index.config import settings
from pursue_index.ocr import llm as ocr_llm

# Polite pacing between LLM calls — some headroom under any observed 429s on
# the OAuth token without dragging the wall-clock too long.
LLM_CALL_DELAY_S = 1.5


def _timed(fn, img):
    """Run ``fn(img)`` returning ``(text, conf, wall_clock_s)``."""
    t0 = time.perf_counter()
    text, conf = fn(img)
    return text, conf, time.perf_counter() - t0


def _llm_cost(captured: dict, candidate: Candidate = DEFAULT_CANDIDATE) -> float:
    return (
        captured.get("input_tokens", 0) / 1_000_000 * candidate.price_input_per_m
        + captured.get("output_tokens", 0) / 1_000_000 * candidate.price_output_per_m
        + captured.get("cache_read", 0) / 1_000_000 * candidate.price_cache_read_per_m
    )


def _llm_one(img, candidate: Candidate = DEFAULT_CANDIDATE) -> tuple[str, float, float, dict, float]:
    """Wrap ``ocr_llm.ocr_image`` so we capture per-call token usage."""
    captured: dict = {}
    original_log = ocr_llm._log_usage

    def capture(usage, _captured=captured):
        _captured["input_tokens"] = getattr(usage, "input_tokens", 0)
        _captured["output_tokens"] = getattr(usage, "output_tokens", 0)
        _captured["cache_read"] = getattr(usage, "cache_read_input_tokens", 0)
        _captured["cache_creation"] = getattr(usage, "cache_creation_input_tokens", 0)
        return original_log(usage)

    ocr_llm._log_usage = capture
    try:
        text, conf, dt = _timed(ocr_llm.ocr_image, img)
    finally:
        ocr_llm._log_usage = original_log

    if not captured:
        return text, conf, dt, {"cache_hit": True, "input_tokens": 0, "output_tokens": 0,
                                "cache_read": 0, "cache_creation": 0}, 0.0
    return text, conf, dt, {**captured, "cache_hit": False}, _llm_cost(captured, candidate)


def run_llm(images, candidate: Candidate = DEFAULT_CANDIDATE, budget: Budget | None = None):
    """OCR each page with ``candidate``'s model, priced at ``candidate``'s rates.

    With a ``budget``, each page is refused (``CapReachedError``) before its call
    when its estimate would take the run past the cap.
    """
    budget = budget if budget is not None else Budget()
    rows = []
    for idx, img in enumerate(images, start=1):
        budget.reserve(estimate_candidate_cost(candidate, 1))
        if idx > 1:
            time.sleep(LLM_CALL_DELAY_S)
        text, conf, dt, tokens, cost = _llm_one(img, candidate)
        budget.add(cost)
        rows.append({"page": idx, "text": text, "confidence": conf,
                     "wall_clock_s": dt, "cost_usd": cost, "tokens": tokens})
    return rows


def run_llm_candidate(images, candidate: Candidate, cache_root: Path | None = None,
                      budget: Budget | None = None) -> list[dict]:
    """Run ``run_llm`` under a different model, in its own cache namespace.

    ``ocr_llm``'s cache key has no model dimension, so a different
    candidate gets its own subdirectory under ``cache_root`` (default
    ``settings.ocr_dir``) rather than replaying the truth proxy's cache.
    """
    root = cache_root if cache_root is not None else settings.ocr_dir
    original_model = settings.ocr_llm_model
    original_cache_dir = ocr_llm._cache_dir
    settings.ocr_llm_model = candidate.model
    ocr_llm._cache_dir = lambda: root / ".llm-cache-benchmark" / candidate.name
    try:
        return run_llm(images, candidate, budget)
    finally:
        settings.ocr_llm_model = original_model
        ocr_llm._cache_dir = original_cache_dir
