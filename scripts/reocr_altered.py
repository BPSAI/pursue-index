"""OCR the post-edit byte versions for the 70 multi-sha PDF cards.

Background: an earlier audit pass exposed 79 cards whose upstream
bytes were silently re-published under the same card_ids (mostly
2026-05-14).
The /altered table + per-card banners + /archive/<sha>.<ext> route
make the preserved bytes reachable, but visitors still have to
compare PDFs manually to see what changed.

This script generates the OCR text for the CURRENT (post-edit)
bytes so the diff builder (Phase 2) can pair it against the pre-edit
OCR already in ``web/public/data/pages-cleaned.json`` (built 2026-05-12
from the pre-overlay versions).

Pipeline:

  1. Read ``web/src/data/byte-history.json``.
  2. For each multi-sha card with a PDF current_entry (skip the 9
     .mp4 cards — OCR doesn't apply to video).
  3. Fetch ``archive/<byte_sha256>.pdf`` from R2.
  4. Rasterize each page via pdf2image.
  5. OCR each page via the existing Anthropic Sonnet 4.6 wrapper
     (``pursue_index.ocr.llm.ocr_image``) — same prompt, same
     cache, same parsing as the canonical ``pursue ocr run`` path.
  6. Write per-card output to ``data/altered-ocr/<card_id>/pages.jsonl``.

Idempotent + resumable: re-running the script skips cards whose
``pages.jsonl`` already has all expected page entries, and resumes
mid-card from the highest page number recorded so far. Operator can
interrupt and resume without re-spending on completed pages.

Cost-capped: ``--max-spend-usd`` (default $90 per the planned budget
envelope) raises ``CostCapExceededError`` mid-run so a budget overrun
fails loud rather than silently consuming the cap.

Reads R2 credentials from CF_ACCOUNT_ID + R2_ACCESS_KEY_ID +
R2_SECRET_ACCESS_KEY (with PURSUE_CF_ACCOUNT_ID fallback per
scripts/r2_archive_assets.py:154).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Auto-load .env so operator can run `python scripts/reocr_altered.py`
# without sourcing first. Matches the implicit loading that
# `pursue_index.config.settings` does via pydantic-settings; this is
# the script-level equivalent for tools that don't go through that
# module.
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    # python-dotenv not installed; operator must `source .env` manually.
    pass

DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_OUT_DIR = _REPO_ROOT / "data" / "altered-ocr"
DEFAULT_BUCKET = "pursue-pdfs"

# Pure helpers + IO wrappers extracted to keep this file under the
# architecture-rules file-size / function-count caps.
from _reocr_helpers import (  # noqa: E402, I001
    CostCapExceededError,
    UsageTracker,
    append_jsonl as _append_jsonl,
    estimate_cost_usd,
    fetch_r2_pdf as _r2_fetch_pdf,
    resume_from_page,
    select_ocr_targets,
    truncate_jsonl_to_valid_prefix,
)

# Re-export for back-compat with tests + downstream consumers.
__all__ = [
    "CostCapExceededError",
    "UsageTracker",
    "estimate_cost_usd",
    "main",
    "ocr_card",
    "resume_from_page",
    "select_ocr_targets",
]


def _ocr_pages_into_jsonl(
    *,
    images: list[Any],
    start_page: int,
    pages_jsonl: Path,
    byte_sha256: str,
    card_id: str,
    ocr_image: Callable[[Any], tuple],
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    """Inner page loop. Extracted from ``ocr_card`` to keep that
    function under the 50-line architecture ceiling."""
    total_pages = len(images)
    for page_no in range(start_page, total_pages + 1):
        if tracker.estimated_cost_usd() > cost_cap_usd:
            raise CostCapExceededError(
                f"estimated cost ${tracker.estimated_cost_usd():.2f}"
                f" exceeds cap ${cost_cap_usd:.2f}"
                f" mid-run on card {card_id} page {page_no}"
            )
        img = images[page_no - 1]
        text, confidence = ocr_image(img)
        _append_jsonl(
            pages_jsonl,
            {
                "page": page_no,
                "text": text,
                "confidence": confidence,
                "byte_sha256": byte_sha256,
            },
        )


def ocr_card(
    *,
    target: dict,
    out_dir: Path,
    r2_client: Any,
    rasterize: Callable[[bytes], list[Any]],
    ocr_image: Callable[[Any], tuple],
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    """OCR every page of a single card, writing pages.jsonl.

    Resume-aware (starts from ``resume_from_page``), idempotent
    (skips when complete), cost-capped (raises ``CostCapExceededError``
    when over). Production wires the dependencies via
    ``_build_real_dependencies``; tests inject mocks.
    """
    card_id = target["card_id"]
    pages_jsonl = out_dir / card_id / "pages.jsonl"
    pdf_bytes = _r2_fetch_pdf(r2_client, target["archive_key"])
    images = rasterize(pdf_bytes)
    # Repair any torn-write prefix BEFORE resuming, otherwise
    # resume_from_page returns 1 forever and we re-spend the full
    # per-card budget on every rerun.
    start_page = truncate_jsonl_to_valid_prefix(pages_jsonl)
    if start_page > len(images):
        # Not silent — could mask a PDF that truncated upstream
        # after we last OCR'd it.
        print(
            f"::notice::card {card_id} already complete"
            f" ({start_page - 1} pages on disk, {len(images)} rendered)"
        )
        return
    _ocr_pages_into_jsonl(
        images=images,
        start_page=start_page,
        pages_jsonl=pages_jsonl,
        byte_sha256=target["byte_sha256"],
        card_id=card_id,
        ocr_image=ocr_image,
        tracker=tracker,
        cost_cap_usd=cost_cap_usd,
    )


# --- Production wiring (only loaded when run as a script) ------------


def _build_real_dependencies(cost_cap_usd: float) -> tuple[Any, Callable, Callable, UsageTracker]:
    """Construct the real R2 client, rasterizer, OCR callable, and
    usage tracker. Kept out of the import path so tests can avoid
    pulling pdf2image / boto3 / anthropic SDK as test-time deps.
    """
    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]
    from r2_archive_assets import make_r2_client  # type: ignore[import-not-found]

    from pursue_index.ocr import llm as pursue_ocr_llm  # type: ignore[import-not-found]

    r2_client = make_r2_client()
    tracker = UsageTracker()

    def rasterize(pdf_bytes: bytes) -> list[Any]:
        # 200 dpi mirrors the canonical OCR pipeline.
        return convert_from_bytes(pdf_bytes, dpi=200)

    def ocr_image(img: Any) -> tuple:
        # Use the with-usage variant so the tracker sees real SDK
        # numbers — replaces the hardcoded 1500/600 estimate that
        # under-counted by ~21% on the canonical OCR run.
        # Cache hits return zero-usage, so tracker never double-counts.
        text, confidence, usage = pursue_ocr_llm.ocr_image_with_usage(img)
        tracker.add(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
        )
        return text, confidence

    return r2_client, rasterize, ocr_image, tracker


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--max-spend-usd",
        type=float,
        default=90.0,
        help="Cost cap; raises CostCapExceededError mid-run if exceeded.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only OCR the first N cards (for dry-runs).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Cards in parallel via ThreadPoolExecutor (default 8).",
    )
    return parser.parse_args(argv)


def _run_card_pool(
    *,
    targets: list[dict],
    out_dir: Path,
    r2_client: Any,
    rasterize: Callable[[bytes], list[Any]],
    ocr_image: Callable[[Any], tuple],
    tracker: UsageTracker,
    cost_cap_usd: float,
    concurrency: int,
) -> list[tuple[str, str]]:
    """Dispatch all targets through a ThreadPoolExecutor. Returns the
    error list. Extracted from main() to stay under the 50-line cap."""
    def _process_one(target: dict) -> tuple[str, str | None]:
        try:
            ocr_card(
                target=target,
                out_dir=out_dir,
                r2_client=r2_client,
                rasterize=rasterize,
                ocr_image=ocr_image,
                tracker=tracker,
                cost_cap_usd=cost_cap_usd,
            )
            return target["card_id"], None
        except CostCapExceededError as exc:
            return target["card_id"], f"CostCapExceededError: {exc}"
        except Exception as exc:
            return target["card_id"], f"{type(exc).__name__}: {exc}"

    completed = 0
    errors: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_process_one, t): t["card_id"] for t in targets}
        for fut in as_completed(futures):
            card_id, err = fut.result()
            completed += 1
            if err:
                errors.append((card_id, err))
                print(f"[{completed}/{len(targets)}] {card_id} ::error:: {err}")
            else:
                print(
                    f"[{completed}/{len(targets)}] {card_id} OK"
                    f" — cost ${tracker.estimated_cost_usd():.2f}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    byte_history = json.loads(args.byte_history.read_text(encoding="utf-8"))
    targets = select_ocr_targets(byte_history)
    if args.limit is not None:
        targets = targets[: args.limit]
    print(f"reocr_altered: {len(targets)} card(s) selected for OCR")
    r2_client, rasterize, ocr_image, tracker = _build_real_dependencies(args.max_spend_usd)
    errors = _run_card_pool(
        targets=targets,
        out_dir=args.out_dir,
        r2_client=r2_client,
        rasterize=rasterize,
        ocr_image=ocr_image,
        tracker=tracker,
        cost_cap_usd=args.max_spend_usd,
        concurrency=args.concurrency,
    )
    print(
        f"reocr_altered: done. total cost ${tracker.estimated_cost_usd():.2f}"
        f" across {tracker.calls} OCR calls"
    )
    if errors:
        print(f"::warning::{len(errors)} card(s) failed:")
        for card_id, err in errors:
            print(f"  {card_id}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
