"""One-shot OCR pass over the PRE-edit byte versions of the altered
cards (Sprint 4j narrow scope).

Background: Sprint 4h's `reocr_altered.py` produced post-edit OCR for
the 70 PDF cards whose upstream bytes were silently re-published. The
diff-builder compared that against the pre-existing
`web/public/data/pages-cleaned.json`, which was produced earlier by a
different vision model — making the diff dominated by model variation.

This script generates **engine-matched** pre-edit OCR using the same
single-pass pipeline that produced the post-edit OCR. Output lands at
`data/altered-ocr-pre/<card_id>/pages.jsonl` and the diff builder
gets pointed at it for the 70 altered PDF cards.

Inputs:
- Bytes: ``<PURSUE_DATA_ROOT>/r2-mirror/archive/<oldest-sha>.pdf``
  (local content-addressed mirror, no R2 fetch). 70 of 79 altered
  cards have a PDF pre-edit version; the other 9 are MP4 (DVIDS
  video, OCR n/a).
- Targets: oldest entry per card in ``web/src/data/byte-history.json``.

Idempotent + cost-capped + resume-aware, identical contract to
``reocr_altered.py``. Uses the canonical ``pursue_index.ocr.llm``
adapter, so envelope-artifact recovery + cache hits + token tracking
all work the same way.

Prereqs: ANTHROPIC_API_KEY in env; ``pursue_index.ocr.llm`` SDK
available; ``PURSUE_DATA_ROOT`` pointing at the data root that holds
``r2-mirror/archive/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SRC_DIR = _REPO_ROOT / "src"
for _p in (_SCRIPTS_DIR, _SRC_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from _reocr_helpers import (  # noqa: E402, I001
    CostCapExceededError,
    UsageTracker,
    append_jsonl,
    estimate_cost_usd,
    resume_from_page,
    truncate_jsonl_to_valid_prefix,
)


DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_OUT_DIR = _REPO_ROOT / "data" / "altered-ocr-pre"
# Resolved at runtime from ``settings.data_root`` so the path tracks
# ``PURSUE_DATA_ROOT`` (default: ./data) rather than baking in an
# operator-specific NAS mount.
DEFAULT_R2_MIRROR: Path | None = None


def select_pre_edit_targets(byte_history: dict, r2_mirror: Path) -> list[dict]:
    """For each multi-sha card with a PDF oldest-entry, return the
    target descriptor. Skips MP4 cards and any whose pre-edit PDF is
    missing from the NAS mirror.
    """
    targets = []
    for card_id, entries in byte_history.items():
        if len(entries) < 2:
            continue  # not altered
        oldest = entries[-1]
        archive_key = oldest.get("archive_key", "")
        if not archive_key.lower().endswith(".pdf"):
            continue  # mp4 cards
        sha = oldest["byte_sha256"]
        pdf_path = r2_mirror / f"{sha}.pdf"
        if not pdf_path.exists():
            print(
                f"::warning::skip {card_id}: pre-edit PDF missing on NAS "
                f"({pdf_path})",
                file=sys.stderr,
            )
            continue
        targets.append({
            "card_id": card_id,
            "byte_sha256": sha,
            "pdf_path": pdf_path,
            "asset_filename": oldest.get("asset_filename") or f"{sha}.pdf",
        })
    return targets


def _ocr_pages(
    *,
    images: list[Any],
    start_page: int,
    pages_jsonl: Path,
    byte_sha256: str,
    card_id: str,
    ocr_image: Any,
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    total_pages = len(images)
    for page_no in range(start_page, total_pages + 1):
        if tracker.estimated_cost_usd() > cost_cap_usd:
            raise CostCapExceededError(
                f"estimated ${tracker.estimated_cost_usd():.2f} "
                f"exceeds cap ${cost_cap_usd:.2f} mid-run on {card_id} "
                f"page {page_no}"
            )
        img = images[page_no - 1]
        text, confidence, usage = ocr_image(img)
        tracker.add(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
        )
        append_jsonl(
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
    rasterize: Any,
    ocr_image: Any,
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    card_id = target["card_id"]
    pages_jsonl = out_dir / card_id / "pages.jsonl"
    pdf_bytes = target["pdf_path"].read_bytes()
    images = rasterize(pdf_bytes)
    # Repair any torn-write before resuming (Sprint 4h fix-pass pattern).
    start_page = truncate_jsonl_to_valid_prefix(pages_jsonl)
    if start_page > len(images):
        print(
            f"::notice::{card_id} already complete "
            f"({start_page - 1}/{len(images)} pages on disk)"
        )
        return
    _ocr_pages(
        images=images,
        start_page=start_page,
        pages_jsonl=pages_jsonl,
        byte_sha256=target["byte_sha256"],
        card_id=card_id,
        ocr_image=ocr_image,
        tracker=tracker,
        cost_cap_usd=cost_cap_usd,
    )


def _build_real_dependencies() -> tuple[Any, Any, UsageTracker]:
    """Wire the production rasterizer + OCR callable + tracker."""
    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]

    from pursue_index.ocr import llm as pursue_ocr_llm  # type: ignore[import-not-found]

    tracker = UsageTracker()

    def rasterize(pdf_bytes: bytes) -> list[Any]:
        return convert_from_bytes(pdf_bytes, dpi=200)

    def ocr_image(img: Any) -> tuple:
        text, confidence, usage = pursue_ocr_llm.ocr_image_with_usage(img)
        return text, confidence, usage

    return rasterize, ocr_image, tracker


def _build_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--r2-mirror",
        type=Path,
        default=None,
        help="Local path holding content-addressed archive bytes. "
        "Defaults to ``<PURSUE_DATA_ROOT>/r2-mirror/archive``.",
    )
    parser.add_argument("--max-spend-usd", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=8)
    return parser


def _run_targets(
    targets: list[dict],
    *,
    out_dir: Path,
    rasterize: Any,
    ocr_image: Any,
    tracker: UsageTracker,
    cost_cap_usd: float,
    concurrency: int,
) -> list[tuple[str, str]]:
    """Dispatch the per-card OCR jobs concurrently. Returns failures."""
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                ocr_card,
                target=t,
                out_dir=out_dir,
                rasterize=rasterize,
                ocr_image=ocr_image,
                tracker=tracker,
                cost_cap_usd=cost_cap_usd,
            ): t for t in targets
        }
        for fut in as_completed(futures):
            target = futures[fut]
            try:
                fut.result()
                cost = tracker.estimated_cost_usd()
                print(
                    f"[done] {target['card_id']} "
                    f"(running total: {tracker.input_tokens:,} in / "
                    f"{tracker.output_tokens:,} out toks, ~${cost:.2f})"
                )
            except CostCapExceededError as exc:
                failures.append((target["card_id"], f"CostCap: {exc}"))
            except Exception as exc:
                failures.append(
                    (target["card_id"], f"{type(exc).__name__}: {exc}")
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    args = _build_args_parser().parse_args(argv)

    if args.r2_mirror is None:
        from pursue_index.config import settings  # type: ignore[import-not-found]
        args.r2_mirror = settings.data_root / "r2-mirror" / "archive"

    bh = json.loads(args.byte_history.read_text())
    targets = select_pre_edit_targets(bh, args.r2_mirror)
    print(f"selected {len(targets)} pre-edit PDF targets")

    rasterize, ocr_image, tracker = _build_real_dependencies()
    failures = _run_targets(
        targets,
        out_dir=args.out_dir,
        rasterize=rasterize,
        ocr_image=ocr_image,
        tracker=tracker,
        cost_cap_usd=args.max_spend_usd,
        concurrency=args.concurrency,
    )

    final = estimate_cost_usd(
        input_tokens=tracker.input_tokens,
        output_tokens=tracker.output_tokens,
    )
    print(
        f"\ndone. total: {tracker.input_tokens:,} in / "
        f"{tracker.output_tokens:,} out toks, ~${final:.4f}"
    )
    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for card_id, msg in failures:
            print(f"  - {card_id}: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
