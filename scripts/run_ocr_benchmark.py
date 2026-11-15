#!/usr/bin/env python3
"""OCR engine A/B harness for the golden set.

For each card listed in ``tests/fixtures/ocr_golden.txt``, rasterizes pages 1-5
once, then runs Tesseract, Surya, and LLM (Anthropic vision) over the same
images. Records per-page text, self-reported confidence, wall-clock, and (for
LLM) token counts. Writes the full per-page detail to
``data/benchmarks/ocr-{timestamp}.json`` so the report and any future
regression check is reproducible.

Run from project root::

    .venv/bin/python scripts/run_ocr_benchmark.py
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
import math
import os
import time
from datetime import UTC, datetime

from pursue_index.paths import repo_root

REPO_ROOT = repo_root()

from _ocr_benchmark_candidates import (
    ADDENDUM_CANDIDATES,
    DEFAULT_CANDIDATE,
    Budget,
    Candidate,
    CapReachedError,
    candidate_for_model,
    dry_run_report,
    engine_lines,
    missing_engines,
)

# Default to Haiku for benchmarks. Sonnet's higher per-token cost isn't
# justified for a comparison run; Haiku produced strong quality lift on
# faded scans in earlier smoke runs. Set BEFORE importing settings so the
# pydantic-settings env load picks it up.
os.environ.setdefault("PURSUE_OCR_LLM_MODEL", "claude-haiku-4-5")

# After the env default above, so the LLM pass sees the same settings.
from _ocr_benchmark_llm import (
    _timed,
    run_llm,
    run_llm_candidate,
)
from pdf2image import convert_from_path

from pursue_index.config import settings
from pursue_index.config.credentials import anthropic_api_key
from pursue_index.download.downloader import asset_path_for
from pursue_index.ocr import pipeline as ocr_pipeline
from pursue_index.ocr import surya as ocr_surya
from pursue_index.scrape import load_manifest

GOLDEN_FILE = REPO_ROOT / "tests" / "fixtures" / "ocr_golden.txt"
MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
OUT_DIR = REPO_ROOT / "data" / "benchmarks"

PAGES_PER_CARD = 5
DPI = 300

def parse_golden() -> list[dict[str, str]]:
    out = []
    for line in GOLDEN_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=2)
        out.append({"card_id": parts[0], "category": parts[1], "description": parts[2]})
    return out


def find_card(manifest, card_id):
    for c in manifest.cards:
        if c.card_id == card_id:
            return c
    raise KeyError(card_id)


def rasterize_first_n(pdf_path: Path, n: int):
    """Render only the first ``n`` pages of the PDF at the configured DPI."""
    return convert_from_path(str(pdf_path), dpi=DPI, first_page=1, last_page=n)


def run_engine_simple(images, fn):
    rows = []
    for idx, img in enumerate(images, start=1):
        text, conf, dt = _timed(fn, img)
        rows.append({"page": idx, "text": text, "confidence": conf, "wall_clock_s": dt, "cost_usd": 0.0})
    return rows


def _summarize_rows(rows, label, extra=""):
    total_t = sum(r["wall_clock_s"] for r in rows)
    mean_c = sum(r["confidence"] for r in rows) / len(rows) if rows else 0
    print(f"    {label}: {total_t:.1f}s total, mean conf {mean_c:.1f}{extra}")


def benchmark_card(card_id: str, entry: dict, manifest, truth: Candidate = DEFAULT_CANDIDATE,
                   budget: Budget | None = None) -> dict | None:
    try:
        card = find_card(manifest, card_id)
    except KeyError:
        print(f"  SKIP {card_id}: not in manifest")
        return None
    pdf_path = asset_path_for(card)
    if not pdf_path or not pdf_path.exists():
        print(f"  SKIP {card_id}: pdf missing at {pdf_path}")
        return None

    print(f"\n=== {card_id} [{entry['category']}] ===")
    t0 = time.perf_counter()
    images = rasterize_first_n(pdf_path, PAGES_PER_CARD)
    print(f"  rasterized {len(images)} pages in {time.perf_counter()-t0:.1f}s")

    print("  tesseract ...")
    tess = run_engine_simple(images, ocr_pipeline.ocr_image)
    _summarize_rows(tess, "tesseract")

    print("  surya ...")
    sur = run_engine_simple(images, ocr_surya.ocr_image)
    _summarize_rows(sur, "surya")

    print(f"  llm ({truth.model}) ...")
    lm = run_llm(images, truth, budget)
    total_cost = sum(r["cost_usd"] for r in lm)
    _summarize_rows(lm, "llm", extra=f", cost ${total_cost:.4f}")

    llm_candidates = {}
    for candidate in ADDENDUM_CANDIDATES:
        print(f"  {candidate.name} ({candidate.model}) ...")
        rows = run_llm_candidate(images, candidate, budget=budget)
        cand_cost = sum(r["cost_usd"] for r in rows)
        _summarize_rows(rows, candidate.name, extra=f", cost ${cand_cost:.4f}")
        llm_candidates[candidate.name] = rows

    return {
        "card_id": card_id,
        "category": entry["category"],
        "description": entry["description"],
        "pdf_filename": pdf_path.name,
        "engines": {"tesseract": tess, "surya": sur, "llm": lm, "llm_candidates": llm_candidates},
    }


def _write_payload(out_path: Path, started_at: datetime, finished_at: datetime,
                   results: list[dict], truth: Candidate = DEFAULT_CANDIDATE,
                   budget: Budget | None = None, stopped: str | None = None) -> None:
    budget = budget if budget is not None else Budget()
    payload = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "pages_per_card": PAGES_PER_CARD,
        "dpi": DPI,
        "llm_model": truth.model,
        "llm_pricing": {"input_per_m": truth.price_input_per_m,
                        "output_per_m": truth.price_output_per_m,
                        "cache_read_per_m": truth.price_cache_read_per_m},
        "hard_cap_usd": budget.cap_usd,
        "spent_usd": budget.spent_usd,
        "stopped_on_cap": stopped,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_all(golden: list[dict], manifest, truth: Candidate, budget: Budget,
             started_at: datetime) -> Path:
    """Benchmark every golden card, checkpointing after each; stop on the cap."""
    checkpoint = OUT_DIR / f"_checkpoint-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    results: list[dict] = []
    stopped: str | None = None
    for g in golden:
        try:
            row = benchmark_card(g["card_id"], g, manifest, truth, budget)
        except CapReachedError as exc:
            # The stopped card's partial rows are dropped, but its calls were
            # billed, so spent_usd keeps them; the payload names the card.
            stopped = f"{exc} (during card {g['card_id']}, which is not in results)"
            print(f"\n{stopped}")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR on {g['card_id']}: {type(exc).__name__}: {exc}")
            row = None
        if row is not None:
            results.append(row)
            # Write a checkpoint after every card so partial progress is preserved.
            _write_payload(checkpoint, started_at, datetime.now(UTC), results, truth, budget)
    out_path = OUT_DIR / f"ocr-{started_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_payload(out_path, started_at, datetime.now(UTC), results, truth, budget, stopped)
    if checkpoint.exists():
        checkpoint.unlink()
    return out_path


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print a per-candidate cost estimate for the v3 document set; no API calls.",
    )
    parser.add_argument(
        "--hard-cap-usd", type=float, default=None,
        help="Stop before the next paid call once it could take total spend past this. "
             "Each call is checked against the larger of its estimate and the costliest "
             "call so far, so spend can pass the cap by at most one call's overrun.",
    )
    args = parser.parse_args(argv)
    if args.hard_cap_usd is not None and not (math.isfinite(args.hard_cap_usd)
                                              and args.hard_cap_usd > 0):
        parser.error("--hard-cap-usd must be a finite amount greater than 0")
    golden = parse_golden()

    if args.dry_run:
        print(dry_run_report(golden, PAGES_PER_CARD))
        return None

    truth = candidate_for_model(settings.ocr_llm_model)
    problems = missing_engines()
    if problems:
        sys.exit("run_ocr_benchmark: an engine can't run here, so the benchmark "
                 "would fail on every card:\n  " + "\n  ".join(problems))
    if not anthropic_api_key():
        sys.exit(
            "ANTHROPIC_API_KEY is not set. Export it (or put it in .env) before "
            "running the benchmark — get a key at https://console.anthropic.com/."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(MANIFEST_PATH)
    print(f"Benchmarking {len(golden)} cards × {PAGES_PER_CARD} pages × "
          f"{2 + 1 + len(ADDENDUM_CANDIDATES)} engines")
    print(engine_lines(truth, args.hard_cap_usd))
    out_path = _run_all(golden, manifest, truth, Budget(args.hard_cap_usd), datetime.now(UTC))
    print(f"\nWrote {out_path}")
    return out_path


if __name__ == "__main__":
    main(sys.argv[1:])
