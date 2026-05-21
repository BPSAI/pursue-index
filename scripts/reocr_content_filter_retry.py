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


_DEFAULT_TARGETS_POST = [
    {
        "card_id": "7d58f0cac741650a",
        "resume_from": 88,
        "byte_sha256": "b13552c6b558408ef1e28a46158e6a45a62d74c3aac6074f74abb23bcab76fbe",
        "archive_key": "archive/b13552c6b558408ef1e28a46158e6a45a62d74c3aac6074f74abb23bcab76fbe.pdf",
        "target_dir": "data/altered-ocr",
    },
    {
        "card_id": "f85532f0514320be",
        "resume_from": 75,
        "byte_sha256": "350806816e58095e0a8f89808fc1af246d6c9a005e63e49e28829b040963a5c2",
        "archive_key": "archive/350806816e58095e0a8f89808fc1af246d6c9a005e63e49e28829b040963a5c2.pdf",
        "target_dir": "data/altered-ocr",
    },
]

# Sprint 4j follow-up: the pre-edit version of the same content-filter
# card also tripped Sonnet on pages 90+ during the corpus alignment run.
# Bytes come from the local NAS r2-mirror (no R2 fetch).
_DEFAULT_TARGETS_PRE = [
    {
        "card_id": "7d58f0cac741650a",
        "resume_from": 90,
        "byte_sha256": "06f96d67fa825b5aefe41bd60e6f3860d71320e2aa436a2bf30240e12c33d0f0",
        "archive_key": "archive/06f96d67fa825b5aefe41bd60e6f3860d71320e2aa436a2bf30240e12c33d0f0.pdf",
        "target_dir": "data/altered-ocr-pre",
    },
]

TARGETS = _DEFAULT_TARGETS_POST  # default; --pre flag swaps to pre-edit targets

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


def _load_pdf_bytes(target: dict, nas_archive: Path | None, r2_client: Any) -> bytes:
    """Prefer local NAS bytes when path is available (Sprint 4j pre-edit
    retry); fall back to R2 fetch for the original Sprint 4i path."""
    if nas_archive is not None:
        nas_pdf = nas_archive / f"{target['byte_sha256']}.pdf"
        if nas_pdf.exists():
            print(
                f"\n[{target['card_id']}] reading PDF from local NAS "
                f"({nas_pdf.name})"
            )
            return nas_pdf.read_bytes()
    print(f"\n[{target['card_id']}] fetching PDF + rasterizing pages...")
    return fetch_r2_pdf(r2_client, target["archive_key"])


def _ocr_pages_via_o4mini(
    *,
    images: list[Any],
    start_page: int,
    pages_jsonl: Path,
    target: dict,
    client: Any,
    model: str,
    tracker: UsageTracker,
    cost_cap_usd: float,
) -> None:
    """Inner page-loop. Extracted so retry_card stays under 50 lines."""
    card_id = target["card_id"]
    total_pages = len(images)
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


def retry_card(
    *,
    target: dict,
    out_dir: Path,
    r2_client: Any,
    client: Any,
    model: str,
    tracker: UsageTracker,
    cost_cap_usd: float,
    nas_archive: Path | None = None,
) -> None:
    card_id = target["card_id"]
    pages_jsonl = out_dir / card_id / "pages.jsonl"
    on_disk = existing_max_page(pages_jsonl)
    start_page = max(on_disk + 1, target["resume_from"])
    pdf_bytes = _load_pdf_bytes(target, nas_archive, r2_client)
    from pdf2image import convert_from_bytes  # type: ignore[import-not-found]
    images = convert_from_bytes(pdf_bytes, dpi=200)
    total_pages = len(images)
    if start_page > total_pages:
        print(f"[{card_id}] already complete ({on_disk}/{total_pages} pages on disk).")
        return
    print(f"[{card_id}] resuming from page {start_page}/{total_pages}.")
    _ocr_pages_via_o4mini(
        images=images,
        start_page=start_page,
        pages_jsonl=pages_jsonl,
        target=target,
        client=client,
        model=model,
        tracker=tracker,
        cost_cap_usd=cost_cap_usd,
    )


def _build_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--max-spend-usd", type=float, default=10.0)
    parser.add_argument(
        "--model",
        default="o4-mini",
        help="OpenAI model id (default o4-mini; fall back to gpt-4o-mini if 404).",
    )
    parser.add_argument(
        "--pre",
        action="store_true",
        help="Run the pre-edit retry targets (Sprint 4j follow-up). Default "
        "is the post-edit targets (Sprint 4i #1).",
    )
    parser.add_argument(
        "--nas-archive",
        type=Path,
        default=None,
        help="Local path holding content-addressed archive bytes. Used as "
        "the PDF source when present; otherwise the script falls back to "
        "R2. Defaults to ``<PURSUE_DATA_ROOT>/r2-mirror/archive``.",
    )
    return parser


def _retry_each(
    targets: list[dict],
    *,
    args: argparse.Namespace,
    client: Any,
    r2_client: Any,
    tracker: UsageTracker,
) -> None:
    for target in targets:
        try:
            retry_card(
                target=target,
                out_dir=args.out_dir,
                r2_client=r2_client,
                client=client,
                model=args.model,
                tracker=tracker,
                cost_cap_usd=args.max_spend_usd,
                nas_archive=args.nas_archive,
            )
        except CostCapExceededError as exc:
            print(f"COST CAP: {exc}", file=sys.stderr)
            break
        except Exception as exc:
            print(
                f"FAILED on {target['card_id']}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    args = _build_args_parser().parse_args(argv)
    if args.nas_archive is None:
        from pursue_index.config import settings  # type: ignore[import-not-found]
        args.nas_archive = settings.data_root / "r2-mirror" / "archive"
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set; cannot dispatch.", file=sys.stderr)
        return 2

    targets = _DEFAULT_TARGETS_PRE if args.pre else _DEFAULT_TARGETS_POST
    if args.out_dir is None:
        args.out_dir = _REPO_ROOT / targets[0]["target_dir"]

    from openai import OpenAI  # type: ignore[import-not-found]
    client = OpenAI()

    r2_client = None
    if not args.nas_archive.exists():
        from r2_archive_assets import make_r2_client  # type: ignore[import-not-found]
        r2_client = make_r2_client()

    tracker = UsageTracker()
    _retry_each(targets, args=args, client=client, r2_client=r2_client, tracker=tracker)

    final_cost = _estimate_cost(tracker)
    print(
        f"\ndone. total: {tracker.input_tokens:,} in / {tracker.output_tokens:,} out toks, "
        f"~${final_cost:.4f} spend"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
