#!/usr/bin/env python3
"""Persistent dots.mocr OCR worker (runs in the isolated dots venv).

Spawned by ``pursue_index.ocr.dots`` (the subprocess-bridge adapter). Loads the
dots.mocr model ONCE, then serves one request per line: read a PNG path on
stdin, write ``{"text": ..., "confidence": ...}`` (one JSON line) on stdout.
On a per-page failure it writes ``{"error": ...}`` and keeps serving; EOF on
stdin ends the loop.

Run by ``$PURSUE_DOTS_PYTHON`` (torch 2.7/cu128 + transformers 4.57.6), NOT
pursue-index's venv. Standalone — imports no pursue_index code.

Bypasses the flash-attn requirement via the model's shipped VisionSdpaAttention
(forced on before construction), so no flash-attn build is needed.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import json
import sys
import types

import torch
from PIL import Image

# --- flash-attn bypass (import transformers FIRST, then neutralise its probe,
# then stub the module so dots' remote `from flash_attn import ...` resolves) ---
from transformers import AutoConfig, AutoModelForCausalLM, AutoProcessor
from transformers.utils import import_utils as _iu

_iu.is_flash_attn_2_available = lambda *a, **k: False
if hasattr(_iu, "is_flash_attn_3_available"):
    _iu.is_flash_attn_3_available = lambda *a, **k: False
if hasattr(_iu, "is_flash_attn_4_available"):
    _iu.is_flash_attn_4_available = lambda *a, **k: False

if "flash_attn" not in sys.modules:
    _stub = types.ModuleType("flash_attn")
    _stub.__spec__ = importlib.machinery.ModuleSpec("flash_attn", loader=None)
    def _no_flash(*a, **k):  # pragma: no cover - never called on the sdpa path
        raise RuntimeError("flash_attn_varlen_func called on the SDPA path")
    _stub.flash_attn_varlen_func = _no_flash
    sys.modules["flash_attn"] = _stub

MAX_EDGE_PX = 1568  # match the bake-off / Sonnet vision input cap

LAYOUT_PROMPT = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""

DROP_CATEGORIES = {"Page-header", "Page-footer", "Picture"}


def layout_json_to_text(raw: str) -> str:
    """Concatenate element text fields in reading order → plain text."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        s = s[4:] if s.startswith("json") else s
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        data = json.loads(s)
    except Exception:
        return raw
    elements = data if isinstance(data, list) else (data.get("elements", []) if isinstance(data, dict) else [])
    if not isinstance(elements, list):
        return raw
    parts = []
    for el in elements:
        if isinstance(el, dict) and el.get("category") not in DROP_CATEGORIES and el.get("text"):
            parts.append(str(el["text"]))
    return "\n".join(parts) if parts else raw


def _resize(img: Image.Image) -> Image.Image:
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    longest = max(rgb.width, rgb.height)
    if longest <= MAX_EDGE_PX:
        return rgb
    scale = MAX_EDGE_PX / longest
    return rgb.resize((int(rgb.width * scale), int(rgb.height * scale)), Image.Resampling.LANCZOS)


def load(model_path: str):
    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    config.attn_implementation = "sdpa"
    if hasattr(config, "vision_config"):
        config.vision_config.attn_implementation = "sdpa"
    model = AutoModelForCausalLM.from_pretrained(
        model_path, config=config, attn_implementation="sdpa",
        torch_dtype=torch.bfloat16, device_map="cuda", trust_remote_code=True,
    )
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    return model, processor


def run_page(model, processor, png_path: str) -> str:
    img = _resize(Image.open(png_path))
    messages = [{"role": "user", "content": [
        {"type": "image", "image": img}, {"type": "text", "text": LAYOUT_PROMPT}]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[img], padding=True, return_tensors="pt").to("cuda")
    for k in ("mm_token_type_ids", "token_type_ids"):
        inputs.pop(k, None)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=8192, do_sample=False)
    trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, out, strict=True)]
    raw = processor.batch_decode(trimmed, skip_special_tokens=True,
                                 clean_up_tokenization_spaces=False)[0]
    return layout_json_to_text(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="dots.mocr model dir (period-free path)")
    args = ap.parse_args()
    print(f"dots_worker: loading {args.model} (sdpa)...", file=sys.stderr, flush=True)
    model, processor = load(args.model)
    print("dots_worker: ready", file=sys.stderr, flush=True)
    for line in sys.stdin:
        png = line.strip()
        if not png:
            break
        try:
            text = run_page(model, processor, png)
            sys.stdout.write(json.dumps({"text": text, "confidence": 0.0}) + "\n")
        except Exception as exc:  # keep serving; report the page error
            sys.stdout.write(json.dumps({"error": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
