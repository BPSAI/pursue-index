"""Scoring of a model's page output against the existing observation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_LEV_CAP = 3000  # characters compared by edit distance
_FIELDS = ("image_type", "description", "visible_text", "observations")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())[:_LEV_CAP]


def text_agreement(a: str, b: str) -> float:
    """1 - normalized Levenshtein distance over whitespace/case-folded text."""
    a, b = _norm(a), _norm(b)
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def _tokens(claim: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", claim.lower()))


def _matches(claim: str, others: list[str], threshold: float = 0.4) -> bool:
    t = _tokens(claim)
    return any(t and (u := _tokens(o)) and len(t & u) / len(t | u) >= threshold
               for o in others)


def claim_overlap(base: list[str] | tuple[str, ...], got: list[str]) -> float:
    """F1 of claims that have a counterpart (token Jaccard >= 0.4) on the other side."""
    if not base and not got:
        return 1.0
    if not base or not got:
        return 0.0
    recall = sum(_matches(c, got) for c in base) / len(base)
    precision = sum(_matches(c, list(base)) for c in got) / len(got)
    return 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)


def completeness(out: Mapping[str, Any]) -> float:
    """Fraction of the four page fields present (``visible_text`` may be empty)."""
    ok = [bool(out.get("image_type")), bool(out.get("description")),
          isinstance(out.get("visible_text"), str), bool(out.get("observations"))]
    return sum(ok) / len(_FIELDS)


def score(base: Any, out: Mapping[str, Any]) -> dict[str, float]:
    claims = [o.get("claim", "") for o in out.get("observations") or [] if isinstance(o, dict)]
    return {"completeness": completeness(out),
            "text_agreement": text_agreement(base.visible_text, str(out.get("visible_text") or "")),
            "claim_overlap": claim_overlap(base.claims, claims)}


def summarize(pages: list[dict[str, Any]], models: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in models:
        every = [p["models"][m] for p in pages if m in p["models"]]
        recs = [r for r in every if "load_error" not in r]
        scored = [r["scores"] for r in recs if r.get("scores")]
        row: dict[str, Any] = {"calls": len(recs), "scored": len(scored),
                               "refusals": sum(r.get("stop_reason") == "refusal" for r in recs),
                               "truncated": sum(r.get("stop_reason") == "max_tokens" for r in recs),
                               "errors": sum("error" in r for r in recs),
                               "load_errors": len(every) - len(recs),
                               "cost_usd": sum(r.get("cost_usd", 0.0) for r in recs)}
        for k in ("completeness", "text_agreement", "claim_overlap"):
            row[k] = sum(s[k] for s in scored) / len(scored) if scored else None
        out[m] = row
    return out
