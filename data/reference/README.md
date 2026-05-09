# Reference Corpora

This directory holds the prior-disclosure reference embedding indexes the
novelty-detection pipeline diffs against. Each reference corpus is a
separate subdirectory with the same shape the embed pipeline writes:

```
data/reference/
└── {archive_id}/
    ├── passages.json      # source-text manifest (corpus-specific)
    └── embeddings/
        └── {model_id}/
            ├── vectors.bin
            └── index.json
```

## Current corpora (v1, launch)

### `synthetic/` — Synthetic Placeholder Reference Corpus

**Status: placeholder. NOT a real coverage claim.**

- **Source**: 10 hand-crafted public-domain UFO-adjacent text passages
  paraphrased from declassified U.S. government records (Roswell 1947
  press releases, Project Blue Book final report summaries, Project
  Sign / Grudge / Hottel memo references, RB-47 1957, Malmstrom 1967,
  Condon Report 1969, AAWSAP/AATIP 2017 disclosures).
- **License**: public domain. No copyright claim from us — paraphrased
  summaries of historical public records.
- **Embeddings**: voyage-3 (1024d, float32). Built by
  `scripts/build_synthetic_reference.py`; falls back to a deterministic
  hash placeholder if `VOYAGE_API_KEY` is not set, so the pipeline is
  exercisable without the API key (but with that fallback the cosine
  scores against the live PURSUE corpus are noise — use the real
  Voyage path for any meaningful comparison).
- **Why a placeholder**: the real reference corpus the
  novelty-detection plan calls for is the Black Vault — a comprehensive
  prior-disclosure FOIA archive on the order of 100k–500k pages.
  Acquiring + OCR'ing + embedding their bulk archive is a separate
  operational task with its own rate-limit + storage concerns, and
  was scoped out of the launch deliverable. This 10-passage hand-crafted
  set is enough to light up the UI and demonstrate the methodology;
  it is **not** a real coverage measurement.

The launch UI shows the matches against this synthetic set with explicit
caveat copy ("reference corpus: small synthetic placeholder; full Black
Vault integration coming"). The methodology page documents the
limitation in plain English.

## Backlog corpora (post-launch)

The novelty-detection plan calls for these reference corpora to be
integrated after launch, in roughly this order:

1. **Black Vault** UAP/UFO archive — the canonical prior-disclosure
   reference. ~100k–500k pages. Embedding cost ~$3–15 with voyage-3;
   storage ~400 MB.
2. **Project Blue Book** archive — already public for decades; many
   FBI 62-HQ-83894 entries probably overlap directly.
3. **NICAP** historical case files — digitized; smaller corpus.
4. **AAWSAP/AATIP** leaked materials — tag separately as "leaked, not
   officially released" provenance.
5. **CIA CREST** declassified records that touch UAP topics.

Each corpus gets a unique `archive_id` so the UI can show "matches:
Black Vault doc 12345" rather than "matches found."

## Adding a new reference corpus

1. Acquire the source documents (mirror locally, respect rate limits).
2. Run them through `pursue scrape` / `pursue download` / `pursue ocr`
   the same way the PURSUE corpus is processed.
3. Run `pursue embed run` over the OCR output to produce
   `embeddings/voyage-3/`.
4. Move the result into `data/reference/{archive_id}/embeddings/voyage-3/`.
5. Re-run `pursue novelty compute` against the new reference.
