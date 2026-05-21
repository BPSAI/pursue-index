"""One-shot OCR retry via OpenAI o4-mini for the 2 Sprint 4h cards
that tripped Sonnet 4.6's content filter (Sprint 4i #1).

Targets, resume points (matches the existing ``pages.jsonl`` state on
disk; the script appends pages ``resume_from`` onwards):

- ``7d58f0cac741650a`` — resume from page 88 of 184 (97 pages remaining).
- ``f85532f0514320be`` — resume from page 75 of 205 (131 pages remaining).

Why this exists: Sprint 4h's canonical OCR pass (Sonnet 4.6 single-pass)
ran into Anthropic's content filter on these 2 cards. The Sprint 4h
banner correctly surfaces partial OCR as truncation; this script is the
retry that uses a different model family (OpenAI o4-mini) whose filter
footprint may pass where Anthropic's didn't.

Prereqs:
- ``OPENAI_API_KEY`` in environment (already in .env).
- ``openai`` package in the venv (added 2026-05-21 for this script).
- ``pdf2image`` (already in the pipeline).
- R2 credentials (same env vars as ``scripts/reocr_altered.py``).

Idempotent + cost-capped: skips pages already present in ``pages.jsonl``;
raises ``CostCapExceededError`` if estimated spend exceeds
``--max-spend-usd`` (default $10, well above the ~$2-5 expected).

Output: appends to the existing ``data/altered-ocr/<card_id>/pages.jsonl``.
The diff-builder run that follows picks up the now-complete OCR and
resolves the "OCR INCOMPLETE" banner on those 2 cards' /altered/ pages.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
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

from _reocr_helpers import (  # noqa: E402
    CostCapExceededError,
    UsageTracker,
    append_jsonl,
    fetch_r2_pdf,
)
from pursue_index.ocr._llm_parsing import parse_response  # noqa: E402


TARGETS = [
    {
        "card_id": "7d58f0cac741650a",
        "resume_from": 88,
        "byte_sha256": "b13552c6b558408ef1e28a46158e6a45a62d74c3aac6074f74abb23bcab76fbe",
        "archive_key": "archive/b13552c6b558408ef1e28a46158e6a45a62d74c3aac6074f74abb23bcab76fbe.pdf",
    },
    {
        "card_id": "f85532f0514320be",
        "resume_from": 75,
        "byte_sha256": "350806816e58095e0a8f89808fc1af246d6c9a005e63e49e28829b040963a5c2",
        "archive_key": "archive/350806816e58095e0a8f89808fc1af246d6c9a005e63e49e28829b040963a5c2.pdf",
    },
]

# Mirrors pursue_index.ocr.llm._SYSTEM_PROMPT verbatim so the OCR
# contract matches the canonical site OCR (same prompt, same expected
# JSON schema). parse_response handles the structured envelope.
_SYSTEM_PROMPT = """You are an expert OCR engine for declassified U.S. government documents \
(typewriter scans, faded carbon copies, multi-column FBI forms, hand-stamped redactions, \
marginalia, and handwritten annotations).

Transcribe every page VERBATIM:
- Preserve original line breaks, spacing, and capitalization.
- Mark any redacted region (black bar, white-out, or "REDACTED" stamp) as [REDACTED].
- Mark any portion you cannot read with reasonable certainty as [ILLEGIBLE].
- Do not summarize, paraphrase, translate, or correct apparent typos.
- Do not add commentary.

Return your response as STRICT JSON with exactly two fields:
{
  "text": "<the verbatim transcription>",
  "confidence": <integer 0-100, your self-rated confidence in the transcription>
}

The "confidence" should reflect how legible the page is and how complete your transcription \
is. A clean typewritten page → 95+. A faded carbon with some illegible patches → 60-75. \
A nearly-blank or noise-only page → 0-20."""

# o4-mini pricing per OpenAI (2026-05-21):
# Input $1.10/MTok, Output $4.40/MTok.
O4_MINI_INPUT_USD_PER_MTOK = 1.10
O4_MINI_OUTPUT_USD_PER_MTOK = 4.40

_MAX_IMAGE_EDGE_PX = 1568


def _image_to_b64_png(img: Any) -> str:
    """Encode PIL image as base64 PNG, resized to the API's preferred edge."""
    from PIL import Image
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    longest = max(rgb.width, rgb.height)
    if longest > _MAX_IMAGE_EDGE_PX:
        scale = _MAX_IMAGE_EDGE_PX / longest
        rgb = rgb.resize(
            (int(rgb.width * scale), int(rgb.height * scale)),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    rgb.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def _estimate_cost(tracker: UsageTracker) -> float:
    """o4-mini pricing applied to the canonical UsageTracker totals."""
    return (
        (tracker.input_tokens / 1_000_000) * O4_MINI_INPUT_USD_PER_MTOK
        + (tracker.output_tokens / 1_000_000) * O4_MINI_OUTPUT_USD_PER_MTOK
    )


def ocr_page_via_o4mini(client: Any, img: Any, model: str) -> tuple[str, float, dict[str, int]]:
    """OCR one page via OpenAI vision; returns (text, confidence, usage)."""
    b64 = _image_to_b64_png(img)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": "Transcribe this page. Respond with only the JSON object.",
                },
            ]},
        ],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    text, confidence = parse_response(raw)
    usage_obj = response.usage
    usage = {
        "input_tokens": getattr(usage_obj, "prompt_tokens", 0),
        "output_tokens": getattr(usage_obj, "completion_tokens", 0),
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }
    return text, confidence, usage


def existing_max_page(jsonl: Path) -> int:
    """Highest page number already in pages.jsonl, or 0 if empty/missing."""
    if not jsonl.exists():
        return 0
    rows = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    return max((row["page"] for row in rows), default=0)


def retry_card(
    *,
    target: dict,
    out_dir: Path,
    r2_client: Any,
    client: Any,
    model: str,
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    card_id = target["card_id"]
    pages_jsonl = out_dir / card_id / "pages.jsonl"

    # The existing pages.jsonl pins pages 1..(resume_from - 1); pick the
    # higher of "what's on disk" and "the documented resume_from" to be
    # safe against a re-run after partial progress.
    on_disk = existing_max_page(pages_jsonl)
    start_page = max(on_disk + 1, target["resume_from"])

    print(f"\n[{card_id}] fetching PDF + rasterizing pages...")
    pdf_bytes = fetch_r2_pdf(r2_client, target["archive_key"])

    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]
    images = convert_from_bytes(pdf_bytes, dpi=200)
    total_pages = len(images)

    if start_page > total_pages:
        print(f"[{card_id}] already complete ({on_disk}/{total_pages} pages on disk).")
        return

    print(f"[{card_id}] resuming from page {start_page}/{total_pages}.")

    for page_no in range(start_page, total_pages + 1):
        cost_now = _estimate_cost(tracker)
        if cost_now > cost_cap_usd:
            raise CostCapExceededError(
                f"estimated ${cost_now:.2f} exceeds cap ${cost_cap_usd:.2f}"
                f" mid-run on {card_id} page {page_no}"
            )
        img = images[page_no - 1]
        try:
            text, confidence, usage = ocr_page_via_o4mini(client, img, model)
        except Exception as exc:
            print(
                f"[{card_id}] page {page_no}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            raise
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
                "byte_sha256": target["byte_sha256"],
            },
        )
        if page_no % 10 == 0 or page_no == total_pages:
            print(
                f"[{card_id}] page {page_no}/{total_pages} "
                f"({tracker.input_tokens:,} in / {tracker.output_tokens:,} out toks, "
                f"~${cost_now:.2f})"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=_REPO_ROOT / "data" / "altered-ocr")
    parser.add_argument("--max-spend-usd", type=float, default=10.0)
    parser.add_argument(
        "--model",
        default="o4-mini",
        help="OpenAI model id (default o4-mini; fall back to gpt-4o-mini if 404).",
    )
    args = parser.parse_args(argv)

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; cannot dispatch.", file=sys.stderr)
        return 2

    from openai import OpenAI  # type: ignore[import-not-found]
    client = OpenAI()

    from r2_archive_assets import make_r2_client  # type: ignore[import-not-found]
    r2_client = make_r2_client()

    tracker = UsageTracker()
    for target in TARGETS:
        try:
            retry_card(
                target=target,
                out_dir=args.out_dir,
                r2_client=r2_client,
                client=client,
                model=args.model,
                tracker=tracker,
                cost_cap_usd=args.max_spend_usd,
            )
        except CostCapExceededError as exc:
            print(f"COST CAP: {exc}", file=sys.stderr)
            break
        except Exception as exc:
            print(
                f"FAILED on {target['card_id']}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            # Continue to next card so partial progress persists.

    final_cost = _estimate_cost(tracker)
    print(
        f"\ndone. total: {tracker.input_tokens:,} in / {tracker.output_tokens:,} out toks, "
        f"~${final_cost:.4f} spend"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
