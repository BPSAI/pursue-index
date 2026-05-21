# OCR cache reproducibility

> Last updated: 2026-05-21 (Sprint 4i #5)

## Why this matters

OCR runs (`pursue ocr run`, `scripts/reocr_altered.py`) cache every
per-page Anthropic vision call to disk by image-content sha256. A
cache hit costs $0; a cache miss costs ~$0.013 per page. The Sprint
4h `reocr_altered` run spent **$46.24** across 3,425 page OCRs. A
fresh checkout on a different host would re-spend that $46 without
the cache.

The cache is the only artifact in the pipeline whose cost is in the
high tens of dollars to regenerate. Everything else — manifests,
embeddings, atlas layouts, OG images — rebuilds in single-digit
minutes from local CPU.

## Where the cache lives

The OCR cache is at `<PURSUE_DATA_ROOT>/ocr/.llm-cache/` — one JSON
file per image-content hash. With the default `PURSUE_DATA_ROOT=./data`
this is `data/ocr/.llm-cache/` (relative to the repo root).

The current operator's setup pins `PURSUE_DATA_ROOT=/mnt/nas/...`, so
the cache lives on the NAS rather than inside the repo checkout. Both
arrangements are valid; the cache's location is purely a function of
`PURSUE_DATA_ROOT`.

## For a fresh checkout

You have three options, in increasing order of cost:

### 1. Mount the existing cache (fastest, $0)

If you have access to the operator's NAS export or a snapshot:

```bash
# Option A — point PURSUE_DATA_ROOT at the existing NAS share
echo 'PURSUE_DATA_ROOT=/path/to/nas/pursue-data' >> .env

# Option B — symlink the cache into a project-local data dir
mkdir -p data/ocr
ln -s /path/to/nas/pursue-data/ocr/.llm-cache data/ocr/.llm-cache
```

Verify with:

```bash
python -c "
from pursue_index.config import settings
from pathlib import Path
cache = settings.ocr_dir / '.llm-cache'
print(f'{cache}: exists={cache.exists()}, '
      f'files={len(list(cache.glob(\"*.json\"))) if cache.exists() else 0}')
"
```

Expect ~3,400 cache files for the current Sprint 4h corpus.

### 2. Re-run with `--max-spend-usd 0` for cache-only mode

You can re-run the OCR pipeline with a $0 cost cap to verify the
cache is correctly populated; any cache miss raises
`CostCapExceededError` before spending a token.

```bash
python scripts/reocr_altered.py --max-spend-usd 0
```

A successful run with $0 spend proves cache completeness for the
altered-OCR corpus.

### 3. Re-OCR from scratch ($46+ in API spend)

If neither of the above is available, re-running the pipeline against
the live R2 bucket will regenerate the cache from scratch. Expect:

- 79 cards × ~43 pages avg = ~3,400 page OCRs
- ~$46 in Anthropic API spend at Sonnet 4.6 input/output rates
- ~2-3 hours wall-clock at the default 8-way concurrency

This is the path most third-party reproducers take.

```bash
ANTHROPIC_API_KEY=<your-key> python scripts/reocr_altered.py
```

## Why the cache isn't committed

The repository commits OCR outputs (per-page transcribed text in
`data/altered-ocr/<card_id>/pages.jsonl`) but NOT the cache itself.
The OCR outputs are what the diff-builder consumes; the cache is
purely an idempotency layer for the OCR call.

Committing the cache would add ~6 MB to the repo and require operators
to rebase that history when the upstream OCR model rev changes. The
trade-off favors leaving the cache out and documenting the recovery
paths.

If reproducibility for outside researchers becomes a priority,
publishing the cache as a separate `pursue-index-ocr-cache` release
artifact (or as an entry in the asset-bytes-registry) is the recommended
escape hatch — see also `.paircoder/plans/autonomous-finds-pipeline.md`
for the broader public-reproducibility posture.
