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
from collections.abc import Callable, Mapping
from dataclasses import asdict
from typing import Any

from _bakeoff_cost import (  # noqa: F401 - re-exported for callers and tests
    DEFAULT_HARD_CAP_USD,
    DEFAULT_PRICES,
    IMAGE_TOKENS,
    PROMPT_TOKENS,
    THINKING_EFFORT,
    THINKING_MODEL,
    call_cost_usd,
    estimate,
    max_tokens_for,
    parse_prices,
    preflight,
    worst_case_call_usd,
)
from _bakeoff_pages import (  # noqa: F401
    BLANK_MAX,
    Baseline,
    build_resolver,
    categorize,
    load_baselines,
    page_key,
    select_sample,
)
from _bakeoff_report import print_plan, write_report
from _bakeoff_scoring import (  # noqa: F401
    claim_overlap,
    completeness,
    score,
    summarize,
    text_agreement,
)

from pursue_index.paths import repo_root

SPOT_CHECK_N = 10
DEFAULT_MODELS = ("claude-opus-4-8", "claude-opus-5-5")
BASELINE_MODEL = "claude-opus-4-8"


def _default_resolver(args: argparse.Namespace) -> Callable[[Baseline], Any]:
    if not args.manifest.exists():
        return lambda _b: None
    from pursue_index.config import settings
    from pursue_index.scrape import load_manifest

    return build_resolver(load_manifest(args.manifest), pdf_dir=settings.pdf_dir,
                          image_dir=settings.image_dir, mirror_dir=settings.r2_mirror_dir,
                          registry=args.registry)


def _call_model(m: str, img: Any, b: Baseline, examine_fn: Callable[..., dict[str, Any]],
                effort: str | None, prices: Mapping[str, tuple[float, float]]) -> tuple[dict[str, Any], float]:
    """One metered call; returns the page record for the model and what it cost."""
    kw: dict[str, Any] = {"model": m, "max_tokens": max_tokens_for(m)}
    if effort and m == THINKING_MODEL:
        kw["effort"] = effort
    try:
        out = examine_fn(img, **kw)
    except Exception as exc:  # noqa: BLE001 - one bad call must not end the run
        return {"error": f"{type(exc).__name__}: {exc}", "scores": None}, worst_case_call_usd(m, prices)
    usage, stop = out.pop("_usage", None), out.pop("_stop_reason", None)
    cost = call_cost_usd(m, usage, prices)
    return {"output": out, "usage": usage, "stop_reason": stop, "cost_usd": cost,
            "scores": None if stop == "refusal" else score(b, out)}, cost


def run_live(sample: list[Baseline], cap: float, examine_fn: Callable[..., dict[str, Any]],
             load_image_fn: Callable[[Any], Any], resolve_fn: Callable[[Baseline], Any],
             effort: str | None, models: tuple[str, ...],
             prices: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    spent, stopped, pages = 0.0, False, []
    for b in sample:
        rec: dict[str, Any] = {"baseline": asdict(b), "models": {}}
        pages.append(rec)
        img, load_error = None, None
        for m in models:
            if spent + worst_case_call_usd(m, prices) > cap:
                stopped = True
                break
            if img is None and load_error is None:
                try:
                    img = load_image_fn(resolve_fn(b))
                except Exception as exc:  # noqa: BLE001 - one bad image must not lose the run
                    load_error = f"{type(exc).__name__}: {exc}"
            if load_error is not None:
                rec["models"][m] = {"load_error": load_error, "scores": None}
                continue
            rec["models"][m], cost = _call_model(m, img, b, examine_fn, effort, prices)
            spent += cost
        if stopped:
            break
    return {"hard_cap_usd": cap, "spent_usd": spent, "stopped_by_cap": stopped,
            "spot_check": [list(page_key(b)) for b in sample[:SPOT_CHECK_N]],
            "pages": pages, "models": list(models), "summary": summarize(pages, models)}


def _parser() -> argparse.ArgumentParser:
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
    ap.add_argument("--effort", choices=("low", "medium", "high"), default=THINKING_EFFORT,
                    help=f"output_config.effort on the {THINKING_MODEL} calls (default {THINKING_EFFORT})")
    ap.add_argument("--manifest", type=Path, default=Path("data/manifests/latest.json"))
    ap.add_argument("--observations-dir", type=Path,
                    default=repo_root() / "web/src/data/image-observations")
    ap.add_argument("--registry", type=Path,
                    default=repo_root() / "data/asset-bytes-registry.jsonl",
                    help="asset byte registry, used to find mirrored PDFs")
    ap.add_argument("--out-dir", type=Path, default=Path("tmp/vision-bakeoff"))
    return ap


def _validate(ap: argparse.ArgumentParser, args: argparse.Namespace
              ) -> tuple[tuple[str, ...], dict[str, tuple[float, float]]]:
    """Check the arguments; returns the arms and the price table, or exits."""
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
    return models, prices


def _run_live_cli(ap: argparse.ArgumentParser, args: argparse.Namespace, sample: list[Baseline],
                  paths: dict[tuple[str, int], str], models: tuple[str, ...],
                  prices: Mapping[str, tuple[float, float]], resolve: Callable[[Baseline], Any],
                  examine_fn: Callable[..., dict[str, Any]] | None,
                  load_image_fn: Callable[[Any], Any] | None) -> int:
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
    write_report(results, paths, args.out_dir)
    print(f"spent ${results['spent_usd']:.2f} of ${args.hard_cap_usd:.2f}; wrote {args.out_dir}")
    print(json.dumps(results["summary"], indent=2))
    return 0


def main(argv: list[str] | None = None, *, examine_fn: Callable[..., dict[str, Any]] | None = None,
         load_image_fn: Callable[[Any], Any] | None = None,
         resolve_fn: Callable[[Baseline], Any] | None = None) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    models, prices = _validate(ap, args)
    resolve = resolve_fn or _default_resolver(args)

    def has_image(b: Baseline) -> bool:
        item = resolve(b)
        return bool(item and item.image_path and Path(item.image_path).exists())

    sample = select_sample(load_baselines(args.observations_dir, BASELINE_MODEL),
                           args.sample_size, args.seed, resolvable=has_image)
    paths = {page_key(b): str(resolve(b).image_path) for b in sample}
    if not args.live:
        print_plan(sample, paths, args.seed, args.hard_cap_usd, models, prices, args.sample_size)
        return 0
    return _run_live_cli(ap, args, sample, paths, models, prices, resolve, examine_fn, load_image_fn)


if __name__ == "__main__":
    sys.exit(main())
