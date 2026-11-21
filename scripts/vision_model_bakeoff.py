#!/usr/bin/env python3
"""Compare vision models on already-described pages (dry-run by default).

Selects a deterministic, seeded sample of pages that already have a vision
observation, runs each page through ``examine_image`` once per model (arm), and
scores each output against the existing observation. See
``docs/vision-model-bakeoff.md`` for the method.

``--dry-run`` (the default) prints the page list, a token and dollar estimate
and the planned cap, and makes no API call. ``--live`` is the only path that
spends: it refuses to start when the arms' summed expected estimate, or any one
arm's worst case, exceeds ``--hard-cap-usd`` (default 8.00), meters each call
from the response's usage, and stops before any call whose worst case would
cross the cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
import os
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from pursue_index.paths import repo_root

DEFAULT_MODELS = ("claude-opus-4-8", "claude-opus-5-5")
BASELINE_MODEL = "claude-opus-4-8"
# (input, output) dollars per million tokens.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0)}
DEFAULT_HARD_CAP_USD = 8.0
# Opus 5.5 always thinks, and thinking tokens count against max_tokens, so it
# gets a larger ceiling than the client's default 2048. 8000 at medium effort
# keeps its worst case under the default cap; a max_tokens stop is recorded.
_THINKING_MODEL = "claude-opus-5-5"
_THINKING_MAX_TOKENS = 8000
_DEFAULT_MAX_TOKENS = 2048
_THINKING_EFFORT = "medium"
IMAGE_TOKENS = 4784  # per image at the client's 1,568px cap
PROMPT_TOKENS = 230 + 20  # system prompt + the user text
EXPECTED_OUTPUT_TOKENS = 700
EXPECTED_THINKING_TOKENS = 1500
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


def select_sample(pool: list[Baseline], n: int, seed: int,
                  resolvable: Callable[[Baseline], bool] | None = None) -> list[Baseline]:
    """Seeded, order-independent, round-robin across image kinds; blanks capped.

    Pages that fail ``resolvable`` are dropped before drawing, so a page with no
    image is replaced by another eligible one and the sample stays full size.
    """
    rng = random.Random(seed)
    ordered = sorted((b for b in pool if resolvable is None or resolvable(b)),
                     key=lambda b: (b.card_id, b.row_key, b.page))
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


def max_tokens_for(model: str) -> int:
    return _THINKING_MAX_TOKENS if model == _THINKING_MODEL else _DEFAULT_MAX_TOKENS


def parse_prices(specs: list[str]) -> dict[str, tuple[float, float]]:
    """Built-in prices overlaid with ``MODEL=IN/OUT`` specs (dollars per MTok)."""
    prices = dict(DEFAULT_PRICES)
    for spec in specs:
        model, sep, rates = spec.partition("=")
        r_in, slash, r_out = rates.partition("/")
        try:
            pair = (float(r_in), float(r_out))
        except ValueError:
            pair = (-1.0, -1.0)
        if not (model and sep and slash) or min(pair) < 0:
            raise ValueError(f"bad --price {spec!r}; expected MODEL=IN/OUT, e.g. claude-x=5/25")
        prices[model] = pair
    return prices


def _usd(prices: Mapping[str, tuple[float, float]], model: str,
         input_tokens: int, output_tokens: int) -> float:
    r_in, r_out = prices[model]
    return (input_tokens * r_in + output_tokens * r_out) / 1e6


def worst_case_call_usd(model: str, prices: Mapping[str, tuple[float, float]]) -> float:
    return _usd(prices, model, IMAGE_TOKENS + PROMPT_TOKENS, max_tokens_for(model))


def call_cost_usd(model: str, usage: Mapping[str, int] | None,
                  prices: Mapping[str, tuple[float, float]]) -> float:
    """Metered cost of one response; a response with no usage costs its worst case."""
    if not usage or not any(usage.get(k) for k in ("input_tokens", "output_tokens")):
        return worst_case_call_usd(model, prices)
    r_in, _ = prices[model]
    cache = (usage.get("cache_creation_input_tokens", 0) * 1.25
             + usage.get("cache_read_input_tokens", 0) * 0.10) * r_in / 1e6
    return _usd(prices, model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)) + cache


def expected_output_tokens(model: str) -> int:
    return EXPECTED_OUTPUT_TOKENS + (EXPECTED_THINKING_TOKENS if model == _THINKING_MODEL else 0)


def estimate(n_pages: int, models: tuple[str, ...],
             prices: Mapping[str, tuple[float, float]]) -> dict[str, dict[str, float | None]]:
    """Per-arm expected and worst-case totals; an arm with no price has ``None`` dollars."""
    rows: dict[str, dict[str, float | None]] = {}
    in_tok = IMAGE_TOKENS + PROMPT_TOKENS
    for m in models:
        out_tok = expected_output_tokens(m)
        priced = m in prices
        per_page = _usd(prices, m, in_tok, out_tok) if priced else None
        rows[m] = {"input_tokens": in_tok, "output_tokens": out_tok, "per_page_usd": per_page,
                   "total_usd": None if per_page is None else n_pages * per_page,
                   "worst_case_total_usd": n_pages * worst_case_call_usd(m, prices) if priced else None}
    return rows


def preflight(est: Mapping[str, Mapping[str, float | None]], cap: float) -> list[str]:
    """Reasons a run must not start; empty means it may.

    Refuses when the arms' summed expected spend exceeds the cap, or any single
    arm's worst case does, or an arm has no price.
    """
    reasons = [f"{m}: no price (pass --price {m}=IN/OUT)" for m, r in est.items()
               if r["total_usd"] is None]
    priced = {m: r for m, r in est.items() if r["total_usd"] is not None}
    total = sum(r["total_usd"] or 0.0 for r in priced.values())
    if total > cap:
        names = ", ".join(priced)
        reasons.append(f"summed expected ${total:.2f} across arms ({names}) exceeds the ${cap:.2f} cap")
    for m, r in priced.items():
        worst = r["worst_case_total_usd"] or 0.0
        if worst > cap:
            reasons.append(f"{m}: worst case ${worst:.2f} exceeds the ${cap:.2f} cap "
                           f"(max_tokens {max_tokens_for(m)})")
    return reasons


def print_plan(sample: list[Baseline], paths: dict[Baseline, str], seed: int, cap: float,
               models: tuple[str, ...], prices: Mapping[str, tuple[float, float]],
               wanted: int) -> None:
    est = estimate(len(sample), models, prices)
    print(f"DRY RUN: no API call is made. {len(sample)} pages, seed {seed}")
    if len(sample) < wanted:
        print(f"WARNING: only {len(sample)} of {wanted} requested pages resolve to an image; "
              "point PURSUE_DATA_ROOT at the data root that holds pdfs/, images/ and r2-mirror/")
    for b in sample:
        print(f"  {b.card_id} p{b.page} [{categorize(b.image_type)}] {paths[b]}")
    for m, r in est.items():
        if r["total_usd"] is None:
            print(f"{m}: NO PRICE; pass --price {m}=IN/OUT (--live refuses without one)")
            continue
        r_in, r_out = prices[m]
        print(f"{m} (${r_in:g}/${r_out:g} per MTok): ~{r['input_tokens']:.0f} input + "
              f"~{r['output_tokens']:.0f} output tokens/page; expected ${r['total_usd']:.2f}; "
              f"worst case ${r['worst_case_total_usd']:.2f} (max_tokens {max_tokens_for(m)})")
    total = sum(r["total_usd"] or 0.0 for r in est.values())
    print(f"summed expected: ${total:.2f}; --hard-cap-usd {cap:.2f}")
    reasons = preflight(est, cap)
    if reasons:
        print("pre-flight REFUSE:")
        for reason in reasons:
            print(f"  - {reason}")
    else:
        print("pre-flight PASS: summed expected and every arm's worst case fit under the cap")


def build_resolver(manifest: Any, *, pdf_dir: Path, image_dir: Path, mirror_dir: Path,
                   registry: Path) -> Callable[[Baseline], Any]:
    """Map a described page to an item the pipeline's renderer can load.

    Any page of a PDF card resolves, not only the image-only ones: the renderer
    rasterizes whatever page it is given. The PDF is the downloaded asset, else
    the mirrored bytes named by the registry's last row for the card.
    """
    from pursue_index.vision.eligibility import EligibleItem, _row_keys

    shas: dict[str, str] = {}
    if registry.exists():
        for line in registry.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("card_id") and row.get("byte_sha256"):
                shas[str(row["card_id"])] = str(row["byte_sha256"])
    groups: dict[str, list[Any]] = {}
    for card in manifest.cards:
        if card.asset_type in ("IMG", "PDF"):
            groups.setdefault(card.card_id, []).append(card)
    keyed = {cid: dict(zip(_row_keys(rows), rows, strict=True)) for cid, rows in groups.items()}

    def resolve(b: Baseline) -> Any:
        card = (keyed.get(b.card_id) or {}).get(b.row_key)
        if card is None or not card.asset_filename:
            return None
        if card.asset_type == "IMG":
            path: Path | None = image_dir / card.card_id / card.asset_filename
            kind = "img_card"
        else:
            path = pdf_dir / card.card_id / card.asset_filename
            if not path.exists() and b.card_id in shas:
                path = mirror_dir / "archive" / f"{shas[b.card_id]}.pdf"
            kind = "image_only_page"
        if path is None or not path.exists():
            return None
        return EligibleItem(card_id=card.card_id, page=b.page if kind != "img_card" else 1,
                            kind=kind, image_path=path, title=card.title, row_key=b.row_key)

    return resolve


def _default_resolver(args: argparse.Namespace) -> Callable[[Baseline], Any]:
    if not args.manifest.exists():
        return lambda _b: None
    from pursue_index.config import settings
    from pursue_index.scrape import load_manifest

    return build_resolver(load_manifest(args.manifest), pdf_dir=settings.pdf_dir,
                          image_dir=settings.image_dir, mirror_dir=settings.r2_mirror_dir,
                          registry=args.registry)


def run_live(sample: list[Baseline], cap: float, examine_fn: Callable[..., dict[str, Any]],
             load_image_fn: Callable[[Any], Any], resolve_fn: Callable[[Baseline], Any],
             effort: str | None, models: tuple[str, ...],
             prices: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    spent, stopped, pages = 0.0, False, []
    for b in sample:
        rec: dict[str, Any] = {"baseline": asdict(b), "models": {}}
        pages.append(rec)
        img = None
        for m in models:
            if spent + worst_case_call_usd(m, prices) > cap:
                stopped = True
                break
            img = img if img is not None else load_image_fn(resolve_fn(b))
            kw: dict[str, Any] = {"model": m, "max_tokens": max_tokens_for(m)}
            if effort and m == _THINKING_MODEL:
                kw["effort"] = effort
            try:
                out = examine_fn(img, **kw)
            except Exception as exc:  # noqa: BLE001 - one bad call must not end the run
                spent += worst_case_call_usd(m, prices)
                rec["models"][m] = {"error": f"{type(exc).__name__}: {exc}", "scores": None}
                continue
            usage, stop = out.pop("_usage", None), out.pop("_stop_reason", None)
            cost = call_cost_usd(m, usage, prices)
            spent += cost
            refused = stop == "refusal"
            rec["models"][m] = {"output": out, "usage": usage, "stop_reason": stop, "cost_usd": cost,
                                "scores": None if refused else score(b, out)}
        if stopped:
            break
    return {"hard_cap_usd": cap, "spent_usd": spent, "stopped_by_cap": stopped,
            "pages": pages, "models": list(models), "summary": summarize(pages, models)}


def summarize(pages: list[dict[str, Any]], models: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in models:
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
    ap.add_argument("--live", action="store_true", help="spend; runs the cap pre-flight first")
    ap.add_argument("--hard-cap-usd", type=float, default=DEFAULT_HARD_CAP_USD,
                    help=f"spend cap (default {DEFAULT_HARD_CAP_USD:.2f})")
    ap.add_argument("--sample-size", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS),
                    help="comma list of Claude model ids, one arm each")
    ap.add_argument("--price", action="append", default=[], metavar="MODEL=IN/OUT",
                    help="dollars per MTok for a model; repeatable (built in for the defaults)")
    ap.add_argument("--effort", choices=("low", "medium", "high"), default=_THINKING_EFFORT,
                    help=f"output_config.effort on the {_THINKING_MODEL} calls (default {_THINKING_EFFORT})")
    ap.add_argument("--manifest", type=Path, default=Path("data/manifests/latest.json"))
    ap.add_argument("--observations-dir", type=Path,
                    default=repo_root() / "web/src/data/image-observations")
    ap.add_argument("--registry", type=Path,
                    default=repo_root() / "data/asset-bytes-registry.jsonl",
                    help="asset byte registry, used to find mirrored PDFs")
    ap.add_argument("--out-dir", type=Path, default=Path("tmp/vision-bakeoff"))
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        ap.error("--live and --dry-run are exclusive")
    if args.hard_cap_usd <= 0:
        ap.error("--hard-cap-usd must be a positive dollar amount")
    if args.live and os.environ.get("CI"):
        ap.error("--live is refused under CI")
    models = tuple(dict.fromkeys(m.strip() for m in args.models.split(",") if m.strip()))
    if not models:
        ap.error("--models needs at least one model id")
    foreign = [m for m in models if not m.startswith("claude-")]
    if foreign:
        ap.error(f"unsupported model(s) {', '.join(foreign)}: only Claude models (ids starting "
                 "with 'claude-') are supported")
    try:
        prices = parse_prices(args.price)
    except ValueError as exc:
        ap.error(str(exc))
    unpriced = [m for m in models if m not in prices]
    if args.live and unpriced:
        ap.error(f"no price for {', '.join(unpriced)}; pass --price MODEL=IN/OUT. Nothing was spent")

    if resolve_fn is None:
        resolve_fn = _default_resolver(args)
    resolve = resolve_fn

    def has_image(b: Baseline) -> bool:
        item = resolve(b)
        return bool(item and item.image_path and Path(item.image_path).exists())

    sample = select_sample(load_baselines(args.observations_dir, BASELINE_MODEL),
                           args.sample_size, args.seed, resolvable=has_image)
    paths = {b: str(resolve(b).image_path) for b in sample}
    if not args.live:
        print_plan(sample, paths, args.seed, args.hard_cap_usd, models, prices, args.sample_size)
        return 0

    if not sample:
        ap.error("no selected page has a local image; nothing was spent")
    reasons = preflight(estimate(len(sample), models, prices), args.hard_cap_usd)
    if reasons:
        ap.error("pre-flight refused; nothing was spent: " + "; ".join(reasons))
    if examine_fn is None:
        from pursue_index.vision.client import examine_image
        examine_fn = examine_image
    if load_image_fn is None:
        from pursue_index.vision.render import load_image_for
        load_image_fn = load_image_for
    results = run_live(sample, args.hard_cap_usd, examine_fn, load_image_fn, resolve, args.effort,
                       models, prices)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "results.json").write_text(json.dumps(results, indent=2))
    write_report(results, {b.card_id: p for b, p in paths.items()}, args.seed, args.out_dir)
    print(f"spent ${results['spent_usd']:.2f} of ${args.hard_cap_usd:.2f}; wrote {args.out_dir}")
    print(json.dumps(results["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
