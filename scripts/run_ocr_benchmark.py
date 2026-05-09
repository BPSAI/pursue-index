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

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Plumb the Claude Code OAuth token into ANTHROPIC_API_KEY if it's not already
# set. The Anthropic Python SDK accepts the OAuth access token verbatim as an
# API key for the Max-tier inference scope.
if "ANTHROPIC_API_KEY" not in os.environ:
    creds_path = Path("/home/david/.claude/.credentials.json")
    if creds_path.exists():
        creds = json.loads(creds_path.read_text())
        os.environ["ANTHROPIC_API_KEY"] = creds["claudeAiOauth"]["accessToken"]

# Default to Haiku for benchmarks: Sonnet on the Max-tier OAuth token hits
# 429 almost immediately for image inference. Haiku has dramatically more
# headroom and the previous LLM smoke showed strong quality lift on faded
# scans even at the smaller tier. Set BEFORE importing settings so the
# pydantic-settings env load picks it up.
os.environ.setdefault("PURSUE_OCR_LLM_MODEL", "claude-haiku-4-5")

from pdf2image import convert_from_path  # noqa: E402

from pursue_index.config import settings  # noqa: E402
from pursue_index.download.downloader import asset_path_for  # noqa: E402
from pursue_index.ocr import llm as ocr_llm  # noqa: E402
from pursue_index.ocr import pipeline as ocr_pipeline  # noqa: E402
from pursue_index.ocr import surya as ocr_surya  # noqa: E402
from pursue_index.scrape import load_manifest  # noqa: E402

GOLDEN_FILE = REPO_ROOT / "tests" / "fixtures" / "ocr_golden.txt"
MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
OUT_DIR = REPO_ROOT / "data" / "benchmarks"

PAGES_PER_CARD = 5
DPI = 300

# Anthropic pricing (per million tokens) — claude-haiku-4-5 in 2026-05.
PRICE_INPUT_PER_M = 1.0
PRICE_OUTPUT_PER_M = 5.0
PRICE_CACHE_READ_PER_M = 0.10  # 10% of input rate

# Polite pacing between LLM calls — some headroom under any observed 429s on
# the OAuth token without dragging the wall-clock too long.
LLM_CALL_DELAY_S = 1.5


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


def _timed(fn, img):
    """Run ``fn(img)`` returning ``(text, conf, wall_clock_s)``."""
    t0 = time.perf_counter()
    text, conf = fn(img)
    return text, conf, time.perf_counter() - t0


def run_engine_simple(images, fn):
    rows = []
    for idx, img in enumerate(images, start=1):
        text, conf, dt = _timed(fn, img)
        rows.append({"page": idx, "text": text, "confidence": conf, "wall_clock_s": dt, "cost_usd": 0.0})
    return rows


def _llm_cost(captured: dict) -> float:
    return (
        captured.get("input_tokens", 0) / 1_000_000 * PRICE_INPUT_PER_M
        + captured.get("output_tokens", 0) / 1_000_000 * PRICE_OUTPUT_PER_M
        + captured.get("cache_read", 0) / 1_000_000 * PRICE_CACHE_READ_PER_M
    )


def _llm_one(img) -> tuple[str, float, float, dict, float]:
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
    return text, conf, dt, {**captured, "cache_hit": False}, _llm_cost(captured)


def run_llm(images):
    rows = []
    for idx, img in enumerate(images, start=1):
        if idx > 1:
            time.sleep(LLM_CALL_DELAY_S)
        text, conf, dt, tokens, cost = _llm_one(img)
        rows.append({"page": idx, "text": text, "confidence": conf,
                     "wall_clock_s": dt, "cost_usd": cost, "tokens": tokens})
    return rows


def _summarize_rows(rows, label, extra=""):
    total_t = sum(r["wall_clock_s"] for r in rows)
    mean_c = sum(r["confidence"] for r in rows) / len(rows) if rows else 0
    print(f"    {label}: {total_t:.1f}s total, mean conf {mean_c:.1f}{extra}")


def benchmark_card(card_id: str, entry: dict, manifest) -> dict | None:
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

    print("  llm ...")
    lm = run_llm(images)
    total_cost = sum(r["cost_usd"] for r in lm)
    _summarize_rows(lm, "llm", extra=f", cost ${total_cost:.4f}")

    return {
        "card_id": card_id,
        "category": entry["category"],
        "description": entry["description"],
        "pdf_filename": pdf_path.name,
        "engines": {"tesseract": tess, "surya": sur, "llm": lm},
    }


def _checkpoint_path(timestamp: str) -> Path:
    return OUT_DIR / f"_checkpoint-{timestamp}.json"


def _write_payload(out_path: Path, started_at: datetime, finished_at: datetime,
                   results: list[dict]) -> None:
    payload = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "pages_per_card": PAGES_PER_CARD,
        "dpi": DPI,
        "llm_model": settings.ocr_llm_model,
        "llm_pricing": {"input_per_m": PRICE_INPUT_PER_M,
                        "output_per_m": PRICE_OUTPUT_PER_M,
                        "cache_read_per_m": PRICE_CACHE_READ_PER_M},
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(MANIFEST_PATH)
    golden = parse_golden()
    print(f"Benchmarking {len(golden)} cards × {PAGES_PER_CARD} pages × 3 engines")

    started_at = datetime.now(UTC)
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    checkpoint = _checkpoint_path(timestamp)
    results: list[dict] = []
    for g in golden:
        try:
            row = benchmark_card(g["card_id"], g, manifest)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR on {g['card_id']}: {type(exc).__name__}: {exc}")
            row = None
        if row is not None:
            results.append(row)
            # Write a checkpoint after every card so partial progress is preserved.
            _write_payload(checkpoint, started_at, datetime.now(UTC), results)

    finished_at = datetime.now(UTC)
    out_path = OUT_DIR / f"ocr-{timestamp}.json"
    _write_payload(out_path, started_at, finished_at, results)
    if checkpoint.exists():
        checkpoint.unlink()
    print(f"\nWrote {out_path}")
    return out_path


if __name__ == "__main__":
    main()
