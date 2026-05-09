"""Pure-function metrics helpers for the OCR benchmark report.

Split out of ``build_ocr_report.py`` to keep its function count under the
arch limit. No external deps, no I/O.
"""

from __future__ import annotations

import re


def _normalize(text: str) -> str:
    """Collapse whitespace, lowercase, strip control chars."""
    return re.sub(r"\s+", " ", text.strip().lower())


def levenshtein(a: list, b: list) -> int:
    """Edit distance over arbitrary token sequences (chars or words)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ai in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, bj in enumerate(b, start=1):
            cost = 0 if ai == bj else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def cer(hyp: str, truth: str) -> float:
    h, t = _normalize(hyp), _normalize(truth)
    if not t:
        return 0.0 if not h else 1.0
    return levenshtein(list(h), list(t)) / max(1, len(t))


def wer(hyp: str, truth: str) -> float:
    h, t = _normalize(hyp).split(), _normalize(truth).split()
    if not t:
        return 0.0 if not h else 1.0
    return levenshtein(h, t) / max(1, len(t))


def truncate(s: str, n: int = 200) -> str:
    s = s.strip().replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


def compute_metrics(results: list[dict]) -> dict:
    """Per-engine aggregates against the LLM truth proxy."""
    agg = {
        "tesseract": _empty_engine_agg(),
        "surya": _empty_engine_agg(),
        "llm": {"pages": 0, "wallclock": 0.0, "conf_sum": 0.0, "cost": 0.0,
                "tokens_in": 0, "tokens_out": 0},
    }
    for card in results:
        for tess, sur, lm in zip(card["engines"]["tesseract"], card["engines"]["surya"],
                                  card["engines"]["llm"], strict=True):
            _accumulate_page(agg, tess, sur, lm)
    return agg


def _empty_engine_agg() -> dict:
    return {"pages": 0, "wallclock": 0.0, "conf_sum": 0.0, "cer_sum": 0.0,
            "wer_sum": 0.0, "cost": 0.0, "cer_list": [], "wer_list": []}


def _accumulate_page(agg: dict, tess: dict, sur: dict, lm: dict) -> None:
    truth = lm["text"]
    for eng, row in (("tesseract", tess), ("surya", sur)):
        a = agg[eng]
        a["pages"] += 1
        a["wallclock"] += row["wall_clock_s"]
        a["conf_sum"] += row["confidence"]
        page_cer = cer(row["text"], truth)
        page_wer = wer(row["text"], truth)
        a["cer_sum"] += page_cer
        a["wer_sum"] += page_wer
        a["cer_list"].append(page_cer)
        a["wer_list"].append(page_wer)
        a["cost"] += row["cost_usd"]
    agg["llm"]["pages"] += 1
    agg["llm"]["wallclock"] += lm["wall_clock_s"]
    agg["llm"]["conf_sum"] += lm["confidence"]
    agg["llm"]["cost"] += lm["cost_usd"]
    tok = lm.get("tokens", {})
    agg["llm"]["tokens_in"] += tok.get("input_tokens", 0)
    agg["llm"]["tokens_out"] += tok.get("output_tokens", 0)


def find_worst_tesseract(results: list[dict]) -> tuple[dict, dict, dict, dict]:
    """Return (card, tess_row, sur_row, llm_row) for the highest-CER tesseract page."""
    worst = None
    for card in results:
        for tess, sur, lm in zip(card["engines"]["tesseract"], card["engines"]["surya"],
                                  card["engines"]["llm"], strict=True):
            page_cer = cer(tess["text"], lm["text"])
            if worst is None or page_cer > worst[0]:
                worst = (page_cer, card, tess, sur, lm)
    _, card, tess, sur, lm = worst
    return card, tess, sur, lm


def projection(agg: dict, results: list[dict], snapshot: list[dict]) -> dict:
    surya_pages = agg["surya"]["pages"]
    sub_threshold = sum(1 for card in results
                         for r in card["engines"]["surya"]
                         if r["confidence"] < 70.0)
    pct = sub_threshold / max(1, surya_pages)
    total_corpus_pages = sum(r["pages"] for r in snapshot) if snapshot else 4153
    llm_pages = agg["llm"]["pages"]
    llm_cost_per_page = agg["llm"]["cost"] / max(1, llm_pages)
    projected_pages = int(total_corpus_pages * pct)
    projected_cost = projected_pages * llm_cost_per_page
    return {
        "surya_pages": surya_pages, "sub_threshold": sub_threshold, "pct": pct,
        "total_corpus_pages": total_corpus_pages, "llm_pages": llm_pages,
        "llm_cost_per_page": llm_cost_per_page,
        "projected_pages": projected_pages, "projected_cost": projected_cost,
        "projected_cost_sonnet": projected_cost * 13.0,
    }
