#!/usr/bin/env python3
"""Apply LLM auto-mode cleanup on top of an existing primary-engine OCR pass.

Production ``pursue ocr run --engine auto --force`` re-rasterizes and
re-OCRs every page from scratch — for a 4k-page corpus that's hours of
GPU time, the bulk of which is wasted re-doing pages whose Surya output
was already above threshold. This script is the surgical fast-path:

  1. Walk every card with ``meta.json status=ok`` and a populated
     ``pages.jsonl``.
  2. For each row whose primary-engine confidence < threshold, render
     just that page from the source PDF and re-OCR it via the LLM.
  3. Rewrite ``pages.jsonl`` in place with the auto-mode row shape (LLM
     text wins, ``primary`` block preserved for transparency).
  4. Update ``meta.json`` so ``engine`` reflects the auto-mode run.

Invocation::

    .venv/bin/python scripts/auto_mode_from_cache.py \\
        --manifest data/manifests/latest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Plumb Claude Code OAuth into ANTHROPIC_API_KEY if not already set, so the
# Anthropic SDK in ocr.llm has credentials. The Max-tier OAuth token works
# verbatim as an API key for the user:inference scope.
if "ANTHROPIC_API_KEY" not in os.environ:
    creds_path = Path("/home/david/.claude/.credentials.json")
    if creds_path.exists():
        creds = json.loads(creds_path.read_text())
        os.environ["ANTHROPIC_API_KEY"] = creds["claudeAiOauth"]["accessToken"]

# Default to Haiku for the cleanup pass — Sonnet on Max-tier OAuth hits 429
# almost immediately on image inference. Set BEFORE importing settings so
# pydantic-settings env loading picks it up.
os.environ.setdefault("PURSUE_OCR_LLM_MODEL", "claude-haiku-4-5")
os.environ.setdefault("PURSUE_OCR_LLM_PROVIDER", "anthropic")

from pdf2image import convert_from_path  # noqa: E402

from pursue_index import get_logger  # noqa: E402
from pursue_index.config import settings  # noqa: E402
from pursue_index.download.downloader import asset_path_for  # noqa: E402
from pursue_index.ocr import auto as ocr_auto  # noqa: E402
from pursue_index.ocr import cached_auto  # noqa: E402
from pursue_index.ocr import llm as ocr_llm  # noqa: E402
from pursue_index.scrape import load_manifest  # noqa: E402

log = get_logger(__name__)


def _render_page(pdf_path: Path, page_idx_1: int, dpi: int):  # type: ignore[no-untyped-def]
    """Rasterize a single PDF page (1-indexed) at ``dpi``."""
    pages = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_idx_1,
        last_page=page_idx_1,
    )
    if not pages:
        raise RuntimeError(f"failed to rasterize page {page_idx_1} of {pdf_path}")
    return pages[0]


def _update_meta(meta_path: Path, primary_engine: str, started_at: datetime,
                 finished_at: datetime, llm_calls: int) -> None:
    """Rewrite meta.json so the engine field reflects the auto-mode upgrade."""
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return
    meta["engine"] = ocr_auto.auto_meta_engine(primary_engine)
    meta["auto_upgrade"] = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": (finished_at - started_at).total_seconds(),
        "llm_calls": llm_calls,
        "threshold": settings.ocr_llm_threshold,
        "model": settings.ocr_llm_model,
    }
    meta_path.write_text(json.dumps(meta, indent=2, default=str))


def _is_card_eligible(meta_path: Path, pages_path: Path) -> str | None:
    """Return primary engine name if eligible, else None (with reason logged)."""
    if not (meta_path.exists() and pages_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return None
    if meta.get("status") != "ok":
        return None
    engine = str(meta.get("engine", ""))
    # If the card has already been auto-upgraded, the engine string starts
    # with "auto:". Skip.
    if engine.startswith("auto:"):
        return None
    if engine in ("surya", "tesseract"):
        return engine
    return None


def upgrade_card(card_id: str, pdf_path: Path, ocr_card_dir: Path) -> tuple[bool, int]:
    """Upgrade one card. Returns ``(ran, llm_calls)``."""
    pages_path = ocr_card_dir / "pages.jsonl"
    meta_path = ocr_card_dir / "meta.json"
    primary_engine = _is_card_eligible(meta_path, pages_path)
    if primary_engine is None:
        log.info("auto_upgrade.skip", card_id=card_id, reason="ineligible")
        return False, 0

    if not pdf_path.exists():
        log.warning("auto_upgrade.skip.missing_pdf", card_id=card_id)
        return False, 0

    started_at = datetime.now(UTC)
    log.info("auto_upgrade.start", card_id=card_id, primary=primary_engine)
    rewrote, llm_calls = cached_auto.upgrade_pages_jsonl(
        pages_path=pages_path,
        pdf_path=pdf_path,
        primary_engine=primary_engine,
        threshold=settings.ocr_llm_threshold,
        render_page=_render_page,
        llm_ocr=ocr_llm.ocr_image,
        dpi=settings.ocr_dpi,
    )
    finished_at = datetime.now(UTC)
    if rewrote:
        _update_meta(meta_path, primary_engine, started_at, finished_at, llm_calls)
    log.info(
        "auto_upgrade.done",
        card_id=card_id,
        rewrote=rewrote,
        llm_calls=llm_calls,
        duration_s=(finished_at - started_at).total_seconds(),
    )
    return rewrote, llm_calls


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, required=True, help="Path to manifest JSON."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most N cards."
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    pdf_cards = [c for c in manifest.cards if c.asset_type == "PDF"]
    if args.limit is not None:
        pdf_cards = pdf_cards[: args.limit]

    log.info(
        "auto_upgrade.start_all",
        cards=len(pdf_cards),
        threshold=settings.ocr_llm_threshold,
        model=settings.ocr_llm_model,
        provider=settings.ocr_llm_provider,
    )
    t0 = time.time()
    cards_upgraded = 0
    total_llm_calls = 0
    for card in pdf_cards:
        pdf_path = asset_path_for(card)
        if pdf_path is None:
            continue
        ocr_card_dir = settings.ocr_dir / card.card_id
        ran, llm_calls = upgrade_card(card.card_id, pdf_path, ocr_card_dir)
        if ran:
            cards_upgraded += 1
        total_llm_calls += llm_calls

    log.info(
        "auto_upgrade.done_all",
        cards_upgraded=cards_upgraded,
        total_llm_calls=total_llm_calls,
        wall_s=round(time.time() - t0, 1),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
