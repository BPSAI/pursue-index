"""Dry-run plan and side-by-side report for the bake-off harness."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from _bakeoff_cost import estimate, max_tokens_for, preflight
from _bakeoff_pages import Baseline, categorize, page_key


def print_plan(sample: list[Baseline], paths: Mapping[tuple[str, int], str], seed: int, cap: float,
               models: tuple[str, ...], prices: Mapping[str, tuple[float, float]],
               wanted: int) -> None:
    est = estimate(len(sample), models, prices)
    print(f"DRY RUN: no API call is made. {len(sample)} pages, seed {seed}")
    if len(sample) < wanted:
        print(f"WARNING: only {len(sample)} of {wanted} requested pages resolve to an image; "
              "point PURSUE_DATA_ROOT at the data root that holds pdfs/, images/ and r2-mirror/")
    for b in sample:
        print(f"  {b.card_id} p{b.page} [{categorize(b.image_type)}] {paths[page_key(b)]}")
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


def _fmt(out: Mapping[str, Any] | None) -> str:
    if not out:
        return "_(no output)_"
    claims = "\n".join(f"  - {o.get('claim')}" for o in out.get("observations") or [])
    return (f"**{out.get('image_type', '')}**\n\n{out.get('description', '')}\n\n"
            f"visible_text: `{out.get('visible_text', '')}`\n\nclaims:\n{claims}")


def _model_body(r: Mapping[str, Any]) -> str:
    if r.get("load_error"):
        return f"load_error: {r['load_error']}"
    return r.get("error") or _fmt(r.get("output"))


def write_report(results: Mapping[str, Any], paths: Mapping[tuple[str, int], str],
                 out_dir: Path) -> None:
    """Side-by-side report; images and spot-check marks are keyed by (card_id, page)."""
    spot = {(c, p) for c, p in results.get("spot_check", [])}
    lines = ["# Vision model bake-off: side by side", "",
             f"Spent ${results['spent_usd']:.2f} of the ${results['hard_cap_usd']:.2f} cap; "
             f"stopped by cap: {results['stopped_by_cap']}.", "",
             "Pages marked SPOT-CHECK are the ten to read by eye.", ""]
    for p in results["pages"]:
        b = p["baseline"]
        key = (b["card_id"], b["page"])
        mark = " (SPOT-CHECK)" if key in spot else ""
        lines += [f"## {b['card_id']} page {b['page']}{mark}", "",
                  f"Image: `{paths.get(key, '')}`", "",
                  f"### Existing observation\n\n{b['image_type']}\n\n{b['description']}\n\n"
                  f"visible_text: `{b['visible_text']}`", ""]
        for m, r in p["models"].items():
            lines += [f"### {m} (stop_reason: {r.get('stop_reason')}, scores: {r.get('scores')})", "",
                      _model_body(r), ""]
    (out_dir / "report.md").write_text("\n".join(lines))
