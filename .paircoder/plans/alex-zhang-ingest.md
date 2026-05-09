---
id: alex-zhang-ingest
type: feature
status: backlog
created: 2026-05-09
priority: medium
depends_on: [embed-stage]
---

# Ingest alex-zhang42 VLM image descriptions as additive retrieval context

## Why

86.6% of our 4,153 source pages have **zero native PDF text** — they're
image-only scans. Our Surya + LLM-fallback OCR captures the *typed
text* off those pages well, but does not describe what the photographs,
sketches, rubber stamps, or handwritten margin notes actually depict.

Hours after we launched, Alex Zhang published
[ufo-pursue-open-atlas](https://huggingface.co/datasets/alex-zhang42/ufo-pursue-open-atlas)
(CC0) — the same DoW Release 01 corpus, re-extracted with mimo-v2.5
(audited by gpt-5.4-mini) where every figure becomes an inline
`*Image: <factual description>*` block. Different angle, same source.
We already credit him in `/methodology#related`. Mounting his image
descriptions alongside our OCR text would meaningfully improve
retrieval on image-heavy pages without adding any net text we
authored — strictly additive, properly cited.

## Identifier mapping

Both projects preserve the war.gov asset URL verbatim:

- **Ours:** `card_id = sha256(asset_url || title)[:16]`
  (`src/pursue_index/scrape/normalize.py::stable_card_id`)
- **Theirs:** `source_url` is a top-level field on every record;
  `page_num` is 1-indexed within that PDF.

The join is mechanical: hash their `source_url` with our function and
match `(card_id, page) ↔ (their_card_id, page_num)`. Their schema also
exposes `sha256` (of the source PDF bytes) which we capture in the
download stage's `meta.json` as a secondary integrity check — useful
as a tiebreaker if any URL was rewritten between fetches.

The bridge wants its own module:
`src/pursue_index/embed/atlas_join.py` — a pure function
`load_atlas_index(corpus_jsonl: Path) -> dict[(card_id, page), list[str]]`
returning the `image_tags` array per page. Test that hashing a sample
of their `source_url` values reproduces card_ids that exist in our
manifest; on the first sample where it doesn't, log loudly and abort
the build (a silent miss is worse than no augmentation).

## Where to inject

**Recommended:** at the `_read_card_pages` boundary in
`src/pursue_index/embed/store.py`. Before computing `text_sha`, append
a deterministic suffix:

```
{ocr_text}

[[IMAGE-DESCRIPTIONS via alex-zhang42/ufo-pursue-open-atlas, mimo-v2.5]]
- {tag_1}
- {tag_2}
...
```

This works because:

- `text_sha` is content-addressed — the moment we change the input
  text the row keys change, and the existing idempotency in
  `embed_run` does the right thing: every augmented page becomes a
  new row, prior rows stay in `index.json` until the build script
  drops them. Forces a clean re-embed; no half-augmented state.
- The injected block is bracketed and human-readable, so query
  responses naturally pull these spans into snippets when image
  content is the actual hit. We should *not* try to embed the image
  descriptions as a separate parallel vector — the chat surface
  scores per-page, and splitting per-page vectors halves our top-k
  signal-to-noise without making citations any more useful.
- The block is detectable by `worker/retrieve.js`'s `makeSnippet` — if
  the query matches inside an image tag, the snippet centers on it.
  No worker-side change required for v1.

**Rejected alternative:** keep ours and theirs as separate vectors with
a `source` flag. Pros: lets us A/B their text against ours.
Cons: doubles the embedding payload (8 MB → ~16 MB on a 10 MB warn
threshold), forces worker-side merging logic, and we'd still need
the join — for half the win.

## Storage and caching

Their `corpus.jsonl` is 14 MB. Ship it in the repo at
`data/external/alex-zhang42-corpus.jsonl` (not on the static-asset
hot path; only used at embed-build time). Pin to a specific HF revision
via a sidecar `data/external/alex-zhang42-corpus.sha256` and record
the revision in the embed `index.json` as a new `augmented_by` field
so a reader can tell which run is augmented and from which snapshot.

Refresh policy: re-pull on every Layer-2 ingest (the auto-poll plan)
and abort the embed run if the new file's hash matches but its row
count drops by more than 5% — we should never silently lose
augmentation coverage.

## Methodology and citation

`/methodology#related` already names the project. Add:

- A short paragraph under `▸ Related work` noting that as of
  2026-05-09, every embedded page that has VLM image descriptions
  available carries an `[[IMAGE-DESCRIPTIONS via …]]` block in the
  embedded text, scored against the same query. Make the dependency
  explicit: their work materially improves our image-page recall.
- A new section on `/cite` recommending citers of those snippets
  reference *both* projects: ours for the retrieval surface, theirs
  for the description text inside the IMAGE block.
- A coverage statistic on `/methodology` once augmentation runs:
  "X / 4,153 pages augmented (Y% of image-only pages)."

This is the right thing regardless of legality (CC0 makes it free) —
the snippets a user reads come partly from his pipeline, and they
should know.

## Embedding cost

4,153 pages × ~600 tok/page (OCR text + ~5–15 image-tag lines) ≈ 2.5M
tokens. Voyage-3 at $0.05/Mtok → **~$0.13**. Well under the $1
per-invocation cap in `embed/pipeline.py`. The chat-side query-time
cost is unchanged.

## Failure modes and fallback

| Failure | Detection | Fallback |
|---|---|---|
| Their schema field renames (e.g. `source_url` → `pdf_url`) | Loader raises on missing key | Abort embed; un-augmented index already shipped, no regression |
| Their `source_url` differs from ours by querystring/case | Card-id miss rate > 1% on the join sample | Abort with a diff log; investigate before forcing through |
| `image_tags` quality drops in a future revision | Spot-check audit score distribution at load time; alert if median drops | Pin to last good revision; do not auto-bump |
| HF dataset taken down | sha256 sidecar mismatch | Use the locally-committed `corpus.jsonl`; site keeps working |
| Conflict between their image text and our OCR (e.g. they describe a stamp our OCR transcribed verbatim) | Acceptable — both add signal. The bracket label tells the model which is which; chat prompt already handles labeled provenance. | n/a |

The conservative fallback is always: skip augmentation, ship our own
text, log that we did. Never inject partial/half-joined data.

## Testing strategy

- **Unit:** join function on a 5-record fixture (3 hits, 1 different
  case, 1 missing). Assert deterministic ordering, no duplicate tags.
- **Integration:** golden test with one well-known image-heavy card —
  the FBI 1947 newspaper-clipping page (their README front-page
  example, page exists in our corpus). Embed both with and without
  augmentation; assert that the query "newspaper clipping priest disc"
  ranks the augmented row higher than the un-augmented baseline.
- **Smoke:** retrieval-side test in `worker/tests/` — assert
  `makeSnippet` selects an `[[IMAGE-DESCRIPTIONS …]]`-anchored span
  when the query matches inside one.

## Acceptance

- [ ] `data/external/alex-zhang42-corpus.jsonl` committed at a pinned
  HF revision; sha256 sidecar matches.
- [ ] `embed/atlas_join.py` joins their records to our card_ids with
  ≥ 99% match rate on shared pages; un-matched pages are logged.
- [ ] `embed_run` accepts an `--augment-from` flag (or settings flag)
  that injects the IMAGE-DESCRIPTIONS block before hashing.
- [ ] `index.json` records `augmented_by` with dataset + revision.
- [ ] `/methodology` shows the augmentation statement and coverage
  count; `/cite` recommends dual citation for IMAGE-block snippets.
- [ ] Golden retrieval test passes.

## Open questions

- **Visibility in the UI.** Should the chat citation footer surface
  "page X augmented with VLM image descriptions" as a tag? Lean yes —
  honest provenance, and users searching for image content deserve to
  know they're reading mimo's words not Surya's. v1.5 follow-up.
- **Surya-vs-VLM disagreement.** If their VLM transcribed a typed
  stamp differently than our OCR, both end up in the embedded text.
  Worth logging the disagreement frequency as a corpus-quality signal,
  but not blocking on it.
- **Coverage on image-only pages.** Their dataset claims 100% page
  coverage; verify on our manifest — if they're missing pages we have
  (or vice versa), surface that on `/methodology`.

## Out of scope

- Re-using their parquet `image` column (the 2 GB JPEG bytes). Our
  retrieval is text-only; we wouldn't bypass embedding to do
  multimodal scoring in v1.
- Mirroring their atlas viewer. They built it; link to it from
  `/methodology`, don't clone it.
- Building our own VLM extraction pipeline. The whole point of this
  plan is to *not* do that work twice.

## Recommendation

**Launch.** The integration is small (one join module, one embed-time
flag, two doc edits), reversible (the un-augmented index can be
republished in one command), cheap (~$0.13 to re-embed), legally
clean (CC0), and properly attributed. The primary risk is identifier
mismatch on a future tranche, which is detectable by the join-sample
gate and fails closed to the un-augmented baseline.
