#!/usr/bin/env python3
"""Compare two vision models on already-described pages (dry-run by default).

Selects a deterministic, seeded sample of pages that already have a vision
observation, runs each page through ``examine_image`` once per model, and
scores each output against the existing observation. See
``docs/vision-model-bakeoff.md`` for the method.

``--dry-run`` (the default) prints the page list, a token and dollar estimate
and the planned cap, and makes no API call. ``--live`` is the only path that
spends: it requires ``--hard-cap-usd``, meters each call from the response's
usage, and stops before any call whose worst case would cross the cap.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Code is loaded from where this script lives, never from the cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

MODELS = ("claude-opus-4-8", "claude-opus-5-5")
BASELINE_MODEL = "claude-opus-4-8"
RATES_PER_MTOK = {"claude-opus-4-8": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0)}
# Opus 5.5 always thinks, and thinking tokens count against max_tokens, so it
# gets a far larger ceiling than the client's default 2048.
MAX_TOKENS = {"claude-opus-4-8": 2048, "claude-opus-5-5": 16000}
IMAGE_TOKENS = 4784  # per image at the client's 1,568px cap
PROMPT_TOKENS = 230 + 20  # system prompt + the user text
EXPECTED_OUTPUT_TOKENS = {"claude-opus-4-8": 700, "claude-opus-5-5": 700 + 1500}  # 5.5: + thinking
BLANK_MAX = 2
_CATEGORIES = ("photograph", "illustration", "document", "other")
_LEV_CAP = 3000  # characters compared by edit distance
_FIELDS = ("image_type", "description", "visible_text", "observations")


@dataclass(frozen=True)
class Baseline:
    card_id: str
    row_key: str
    page: int
    image_type: str
    description: str
    visible_text: str
    claims: tuple[str, ...]


def load_baselines(obs_dir: Path, model: str) -> list[Baseline]:
    """Described pages from sidecars whose ``our_pass.model`` is ``model``."""
    out: list[Baseline] = []
    for path in sorted(obs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or (data.get("our_pass") or {}).get("model") != model:
            continue
        for page in data.get("pages") or []:
            desc = page.get("description") if isinstance(page, dict) else None
            if not isinstance(desc, str) or not desc.strip():
                continue
            claims = tuple(o["claim"] for o in page.get("observations") or []
                           if isinstance(o, dict) and isinstance(o.get("claim"), str))
            out.append(Baseline(
                str(data.get("card_id") or path.stem), str(page.get("row_key") or ""),
                int(page.get("page") or 1), str(page.get("image_type") or ""), desc,
                str(page.get("visible_text") or ""), claims))
    return sorted(out, key=lambda b: (b.card_id, b.row_key, b.page))


def categorize(image_type: str) -> str:
    t = image_type.lower()
    if "blank" in t or "empty" in t:
        return "blank"
    if re.search(r"illustrat|render|drawing|diagram", t):
        return "illustration"
    if re.search(r"photo", t):
        return "photograph"
    if re.search(r"scan|document|page|text|letter|memo|form", t):
        return "document"
    return "other"


def select_sample(pool: list[Baseline], n: int, seed: int) -> list[Baseline]:
    """Seeded, order-independent, round-robin across image kinds; blanks capped."""
    rng = random.Random(seed)
    ordered = sorted(pool, key=lambda b: (b.card_id, b.row_key, b.page))
    buckets: dict[str, list[Baseline]] = {c: [] for c in (*_CATEGORIES, "blank")}
    for b in ordered:
        buckets[categorize(b.image_type)].append(b)
    for name in buckets:
        rng.shuffle(buckets[name])
    blanks = buckets.pop("blank")[: min(BLANK_MAX, n)]
    picked: list[Baseline] = []
    want = n - len(blanks)
    while len(picked) < want and any(buckets.values()):
        for name in _CATEGORIES:
            if buckets[name] and len(picked) < want:
                picked.append(buckets[name].pop())
    return sorted(picked + blanks, key=lambda b: (b.card_id, b.row_key, b.page))


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


def score(base: Baseline, out: Mapping[str, Any]) -> dict[str, float]:
    claims = [o.get("claim", "") for o in out.get("observations") or [] if isinstance(o, dict)]
    return {"completeness": completeness(out),
            "text_agreement": text_agreement(base.visible_text, str(out.get("visible_text") or "")),
            "claim_overlap": claim_overlap(base.claims, claims)}


def _usd(model: str, input_tokens: int, output_tokens: int) -> float:
    r_in, r_out = RATES_PER_MTOK[model]
    return (input_tokens * r_in + output_tokens * r_out) / 1e6


def worst_case_call_usd(model: str) -> float:
    return _usd(model, IMAGE_TOKENS + PROMPT_TOKENS, MAX_TOKENS[model])


def call_cost_usd(model: str, usage: Mapping[str, int] | None) -> float:
    """Metered cost of one response; a response with no usage costs its worst case."""
    if not usage or not any(usage.get(k) for k in ("input_tokens", "output_tokens")):
        return worst_case_call_usd(model)
    r_in, _ = RATES_PER_MTOK[model]
    cache = (usage.get("cache_creation_input_tokens", 0) * 1.25
             + usage.get("cache_read_input_tokens", 0) * 0.10) * r_in / 1e6
    return _usd(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)) + cache


def estimate(n_pages: int) -> dict[str, dict[str, float]]:
    rows = {}
    for m in MODELS:
        in_tok = IMAGE_TOKENS + PROMPT_TOKENS
        rows[m] = {"input_tokens": in_tok, "output_tokens": EXPECTED_OUTPUT_TOKENS[m],
                   "per_page_usd": _usd(m, in_tok, EXPECTED_OUTPUT_TOKENS[m]),
                   "total_usd": n_pages * _usd(m, in_tok, EXPECTED_OUTPUT_TOKENS[m]),
                   "worst_case_total_usd": n_pages * worst_case_call_usd(m)}
    return rows


def suggested_cap(est: Mapping[str, Mapping[str, float]]) -> float:
    return float(max(1, math.ceil(2 * sum(r["total_usd"] for r in est.values()))))


def print_plan(sample: list[Baseline], paths: dict[Baseline, str], seed: int,
               cap: float | None) -> None:
    est = estimate(len(sample))
    print(f"DRY RUN: no API call is made. {len(sample)} pages, seed {seed}")
    for b in sample:
        print(f"  {b.card_id} p{b.page} [{categorize(b.image_type)}] {paths[b]}")
    for m, r in est.items():
        print(f"{m}: ~{r['input_tokens']:.0f} input + ~{r['output_tokens']:.0f} output "
              f"tokens/page; ~${r['per_page_usd']:.3f}/page; ~${r['total_usd']:.2f} total "
              f"(worst case ${r['worst_case_total_usd']:.2f}; max_tokens {MAX_TOKENS[m]})")
    total = sum(r["total_usd"] for r in est.values())
    print(f"estimated total: ${total:.2f} at $5/$25 (Opus 4.8) and $4/$20 (Opus 5.5) per MTok")
    print(f"planned --hard-cap-usd: {cap if cap is not None else suggested_cap(est)}")


def _resolver(manifest: Path) -> Callable[[Baseline], Any]:
    if not manifest.exists():
        return lambda _b: None
    from pursue_index.config import settings
    from pursue_index.scrape import load_manifest
    from pursue_index.vision.eligibility import select_eligible

    by_key = {i.coverage_key: i for i in select_eligible(load_manifest(manifest), None, settings.ocr_dir)}
    return lambda b: by_key.get((b.card_id, b.row_key, b.page))


def run_live(sample: list[Baseline], cap: float, examine_fn: Callable[..., dict[str, Any]],
             load_image_fn: Callable[[Any], Any], resolve_fn: Callable[[Baseline], Any],
             effort: str | None) -> dict[str, Any]:
    spent, stopped, pages = 0.0, False, []
    for b in sample:
        rec: dict[str, Any] = {"baseline": asdict(b), "models": {}}
        pages.append(rec)
        img = None
        for m in MODELS:
            if spent + worst_case_call_usd(m) > cap:
                stopped = True
                break
            img = img if img is not None else load_image_fn(resolve_fn(b))
            kw: dict[str, Any] = {"model": m, "max_tokens": MAX_TOKENS[m]}
            if effort and m == "claude-opus-5-5":
                kw["effort"] = effort
            try:
                out = examine_fn(img, **kw)
            except Exception as exc:  # noqa: BLE001 - one bad call must not end the run
                spent += worst_case_call_usd(m)
                rec["models"][m] = {"error": f"{type(exc).__name__}: {exc}", "scores": None}
                continue
            usage, stop = out.pop("_usage", None), out.pop("_stop_reason", None)
            cost = call_cost_usd(m, usage)
            spent += cost
            refused = stop == "refusal"
            rec["models"][m] = {"output": out, "usage": usage, "stop_reason": stop, "cost_usd": cost,
                                "scores": None if refused else score(b, out)}
        if stopped:
            break
    return {"hard_cap_usd": cap, "spent_usd": spent, "stopped_by_cap": stopped,
            "pages": pages, "summary": summarize(pages)}


def summarize(pages: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in MODELS:
        recs = [p["models"][m] for p in pages if m in p["models"]]
        scored = [r["scores"] for r in recs if r.get("scores")]
        row: dict[str, Any] = {"calls": len(recs), "scored": len(scored),
                               "refusals": sum(r.get("stop_reason") == "refusal" for r in recs),
                               "truncated": sum(r.get("stop_reason") == "max_tokens" for r in recs),
                               "errors": sum("error" in r for r in recs),
                               "cost_usd": sum(r.get("cost_usd", 0.0) for r in recs)}
        for k in ("completeness", "text_agreement", "claim_overlap"):
            row[k] = sum(s[k] for s in scored) / len(scored) if scored else None
        out[m] = row
    return out


def _fmt(out: Mapping[str, Any] | None) -> str:
    if not out:
        return "_(no output)_"
    claims = "\n".join(f"  - {o.get('claim')}" for o in out.get("observations") or [])
    return (f"**{out.get('image_type', '')}**\n\n{out.get('description', '')}\n\n"
            f"visible_text: `{out.get('visible_text', '')}`\n\nclaims:\n{claims}")


def write_report(results: dict[str, Any], paths: dict[str, str], seed: int, out_dir: Path) -> None:
    spot = {b.card_id for b in select_sample(
        [Baseline(**{**p["baseline"], "claims": tuple(p["baseline"]["claims"])}) for p in results["pages"]],
        10, seed)}
    lines = ["# Vision model bake-off: side by side", "",
             f"Spent ${results['spent_usd']:.2f} of the ${results['hard_cap_usd']:.2f} cap; "
             f"stopped by cap: {results['stopped_by_cap']}.", "",
             "Pages marked SPOT-CHECK are the ten to read by eye.", ""]
    for p in results["pages"]:
        b = p["baseline"]
        mark = " (SPOT-CHECK)" if b["card_id"] in spot else ""
        lines += [f"## {b['card_id']} page {b['page']}{mark}", "",
                  f"Image: `{paths.get(b['card_id'], '')}`", "",
                  f"### Existing observation\n\n{b['image_type']}\n\n{b['description']}\n\n"
                  f"visible_text: `{b['visible_text']}`", ""]
        for m, r in p["models"].items():
            lines += [f"### {m} (stop_reason: {r.get('stop_reason')}, scores: {r.get('scores')})", "",
                      r.get("error") or _fmt(r.get("output")), ""]
    (out_dir / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None, *, examine_fn: Callable[..., dict[str, Any]] | None = None,
         load_image_fn: Callable[[Any], Any] | None = None,
         resolve_fn: Callable[[Baseline], Any] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan only (the default)")
    ap.add_argument("--live", action="store_true", help="spend; requires --hard-cap-usd")
    ap.add_argument("--hard-cap-usd", type=float)
    ap.add_argument("--sample-size", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--effort", choices=("low", "medium", "high"),
                    help="send output_config.effort on the Opus 5.5 calls")
    ap.add_argument("--manifest", type=Path, default=Path("data/manifests/latest.json"))
    ap.add_argument("--observations-dir", type=Path,
                    default=Path(__file__).resolve().parents[1] / "web/src/data/image-observations")
    ap.add_argument("--out-dir", type=Path, default=Path("tmp/vision-bakeoff"))
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        ap.error("--live and --dry-run are exclusive")
    if args.live and (args.hard_cap_usd is None or args.hard_cap_usd <= 0):
        ap.error("--live requires --hard-cap-usd (a positive dollar cap)")
    if args.live and os.environ.get("CI"):
        ap.error("--live is refused under CI")

    sample = select_sample(load_baselines(args.observations_dir, BASELINE_MODEL),
                           args.sample_size, args.seed)
    resolve = resolve_fn or _resolver(args.manifest)
    items = {b: resolve(b) for b in sample}
    paths = {b: str(i.image_path) if i and i.image_path else "(asset not resolved)"
             for b, i in items.items()}
    if not args.live:
        print_plan(sample, paths, args.seed, args.hard_cap_usd)
        return 0

    missing = [b.card_id for b, i in items.items() if not (i and i.image_path and Path(i.image_path).exists())]
    if missing:
        ap.error(f"{len(missing)} selected pages have no local image; nothing was spent")
    if examine_fn is None:
        from pursue_index.vision.client import examine_image
        examine_fn = examine_image
    if load_image_fn is None:
        from pursue_index.vision.render import load_image_for
        load_image_fn = load_image_for
    results = run_live(sample, args.hard_cap_usd, examine_fn, load_image_fn, resolve, args.effort)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "results.json").write_text(json.dumps(results, indent=2))
    write_report(results, {b.card_id: p for b, p in paths.items()}, args.seed, args.out_dir)
    print(f"spent ${results['spent_usd']:.2f} of ${args.hard_cap_usd:.2f}; wrote {args.out_dir}")
    print(json.dumps(results["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
