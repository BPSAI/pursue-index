---
name: Surya emits HTML bold/underline tags even with math_mode=False
description: Surya 0.17 wraps inferred bold/underline runs in <b>/<u>/<i> tags regardless of math_mode. Strip at the search-payload boundary, not in ocr/surya.py — keep raw model output in pages.jsonl.
type: project
---

Surya 0.17's recognition predictor outputs HTML-style markup
(`<b>...</b>`, `<u>...</u>`, occasionally `<i>...</i>`) around inferred
bold/underline runs even with `math_mode=False`. The corpus has no
markup semantics so this is noise downstream — but the PURSUE corpus is
declassified gov docs where headers and stamps are bold and that's
exactly what gets wrapped.

**Why:** The `ocr-gpu-surya.md` plan flagged this as follow-up #2.
Verified during the full Surya pass: 19 `<b>` tags in a single 184-page
FBI section, ~1 every 10 pages on average. Disabling `math_mode` (which
v1 did) doesn't strip these — they're emitted by a different code path.

**How to apply:**
- **Don't** strip in `src/pursue_index/ocr/surya.py`. The right layering
  is to keep raw model output in `pages.jsonl` so downstream consumers
  (search, embed, future analysis) can choose how much markup to keep.
- **Do** strip at the search-payload boundary in
  `scripts/build_search_data.py` via a regex like
  `re.compile(r"</?(?:b|u|i)>")`. This is what landed in commit
  `8dcb640` and closes follow-up #2.
- The embed stage will need the same strip applied to its text input
  before tokenization (otherwise embeddings include `<b>` token noise).
  Add the strip to `scripts/build_embed_data.py` or to whatever module
  feeds text into the embedder.
