---
name: pursue ocr run --engine auto --force re-OCRs every page from scratch
description: Auto-mode `--force` on `pursue ocr run` does NOT cache primary-engine pages on a re-run; for sub-threshold-only LLM cleanup, use scripts/auto_mode_from_cache.py instead.
type: feedback
---

`pursue ocr run --engine auto --force` re-rasterizes the PDF and re-runs
the primary engine (Surya) on every page from scratch, then LLM-fallbacks
for sub-threshold ones. On the 4153-page corpus that's ~3-4 h GPU time
even though most pages already have good Surya output on disk.

**Use the cache-aware path when applying LLM cleanup over an existing
primary-engine corpus:**

```bash
# Plumbs Claude Code OAuth automatically; defaults to Haiku.
.venv/bin/python scripts/auto_mode_from_cache.py \
  --manifest data/manifests/latest.json
```

This walks every card with `meta.json status=ok` + `engine in {surya, tesseract}`,
renders ONLY the sub-threshold pages from the source PDF, calls the LLM
on those, and rewrites pages.jsonl in place using the auto-mode row
shape (LLM text wins, primary block preserved).

**Why:** The cache-aware path took 38 min wall-clock on the 4153-page
corpus for $1.60 at Haiku; the equivalent `--force` run was projected
at 3+ hours. First-author also discovered that killing a `--force`
mid-run truncates pages.jsonl to 0 bytes (idempotency check is on
meta.json which was never updated), requiring a follow-up
`pursue ocr run --engine surya` pass for that single card before the
cache-aware upgrade can pick it up.

**How to apply:** When the user asks for "auto-mode full corpus pass"
or similar, default to the cached_auto path. Reserve `--force` for
when you need to actually replace primary-engine output with
something different (e.g., a Surya version upgrade).

**Note on Anthropic prompt caching:** `cache_control=ephemeral` in
`ocr/llm.py` is currently inactive because the system prompt is ~300
tokens, below Anthropic's 1024-token minimum. `cache_read_tokens=0`
across all 591 calls in the live pass. Not a blocker; just no extra
discount on top of the per-image SHA cache.
