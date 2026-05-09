---
id: novelty-detection
type: feature
status: shipped-machinery-only
created: 2026-05-08
updated: 2026-05-09
priority: high
depends_on: [embed-stage]
---

# Novelty detection — "new vs. previously disclosed"

## Status (2026-05-09)

**Machinery + UI surface: shipped.** `pursue novelty compute` produces
the per-card disclosure status sidecar; `scripts/build_novelty_data.py`
emits the in-browser payload; the CardExplorer index page has a
DISCLOSURE filter chip + per-card pills; the card detail page has a
Provenance panel with top-3 reference matches + honest caveat copy;
the methodology page documents the rules + thresholds + reference
corpora.

**Reference corpus: synthetic placeholder, NOT a coverage claim.**
The integrated v1 reference is 10 hand-crafted public-domain UFO-adjacent
text passages embedded with voyage-3 (see `data/reference/synthetic/`).
This is enough to light up the UI and demonstrate the methodology;
it is **not** a real coverage measurement. Top-similarity matches
already surface the right kind of content (FBI 62-HQ-83894 sections
match the FBI Hottel memo + Project Blue Book summary in the placeholder
corpus at ~0.79 cosine), but with only 10 reference passages the
0.85 "previously-disclosed" threshold is not crossed by any card —
which is correct behavior for a placeholder.

**Next step (post-launch):** acquire + OCR + embed the Black Vault
bulk archive (~100k–500k pages, ~$3–15 voyage-3 cost, ~24h Surya OCR
on the 5090, ~400 MB storage). Once the index lives at
`data/reference/blackvault/embeddings/voyage-3/`, re-running
`pursue novelty compute --reference data/reference/blackvault/...`
gives every existing card a meaningful disclosure status without
any user-facing change. The launch credibility comes from the
machinery being built and visible, not from full Black Vault
coverage on day one.



## Why

The hardcore UAP audience reads any new disclosure with one question:
**how much of this was already in the wild?**

Right now, no one is answering that question programmatically. Every
prior FOIA archive (Black Vault, NICAP, MUFON case files, AAWSAP/AATIP
leaks, etc.) sits in its own silo. When DOW drops a tranche, journalists
write "X new documents released" — but a meaningful chunk of "X" is
usually re-releases of material from the 1990s Black Vault FOIAs.

If we ship the only tool that says **"of these 161 cards, 73 are
genuinely new and 88 substantially overlap with prior public archives"**
and shows the receipts, that's the citation moat. It's the feature
serious researchers and skeptics both want, and nobody else has it.

It's also the feature that compounds: every future tranche gets the
same treatment automatically, and the prior-tranche material becomes
part of the reference corpus over time.

## Approach

The plumbing already exists once `embed-stage.md` ships. Reuse it.

1. **Acquire reference corpus.** Start with the Black Vault — the
   biggest single archive of prior UAP FOIA releases. Their bulk
   archive is downloadable. Respect rate limits; cache aggressively;
   keep a local mirror under `{data_root}/reference/blackvault/`.
2. **Run the same pipeline** over it: `pursue scrape` (or a one-off
   ingest), `pursue download`, `pursue ocr` (Surya preferred — same
   engine as PURSUE so OCR drift is minimized), `pursue embed`.
3. **Compare per-page.** For each PURSUE page vector, cosine-similarity
   against the Black Vault index. Top-1 match gives us the closest
   prior disclosure; threshold at e.g. 0.85 → "previously disclosed,"
   0.70–0.85 → "partial overlap," <0.70 → "novel."
4. **Aggregate at card level.** A card is:
   - `novel` — >70% of pages score below the partial-overlap threshold.
   - `partial` — mixed; some new content, some prior material.
   - `previously-disclosed` — most pages have high-similarity matches.
5. **Tag the manifest.** Add a `disclosure_status` field per card and
   a `novelty_score: 0..1` (page-aggregate). Re-run on tranche update.
6. **UI surface:**
   - **Index filter chip:** "NEW DISCLOSURES ONLY" — show only cards
     marked novel + partial.
   - **Card detail "Provenance" section:** for each non-novel page,
     show top-3 closest matches with similarity score, source archive,
     and a link to the matching document.
   - **Stats on the home page:** "of N cards, X% are new disclosures,
     Y% substantially overlap with prior FOIA archives."

## Reference corpora to add

Phase 1 (launch):
- **Black Vault** UAP/UFO archive — comprehensive FBI + DOD prior FOIA.

Phase 2 (post-launch, as time permits):
- **NICAP** historical case files (digitized; smaller).
- **AAWSAP/AATIP** leaked materials (more contested provenance; tag
  separately as "leaked, not officially released").
- **Project Blue Book** archive (already public for decades; many of
  the FBI 62-HQ-83894 entries probably overlap).
- **CIA CREST** declassified records that touch UAP topics.

Each reference corpus gets a unique `archive_id` so the UI can show
"matches: Black Vault doc 12345" rather than just "matches found."

## Acceptance

- `pursue novelty run --manifest data/manifests/latest.json --reference blackvault`
  produces per-card `disclosure_status` + `novelty_score` and writes
  them into a sidecar `data/novelty/latest.json` (or directly into the
  manifest with a v3 schema bump).
- Index page filter shows only novel+partial cards when toggled.
- Card detail "Provenance" section shows the closest matches when the
  card is non-novel.
- A "% new disclosures" stat appears on the home page in the hero
  panel.
- Methodology page documents the approach, the threshold values, the
  reference corpora used, and known limitations (OCR drift, redaction
  variance).

## Editorial standards

- **Don't over-claim.** "Substantially overlaps with Black Vault doc X"
  is honest; "previously disclosed" without qualification is too
  strong if the overlap is partial.
- **Show the receipts.** Every "previously disclosed" tag links to the
  matching prior document. No invisible algorithmic judgments.
- **Surface false positives.** A reviewer queue for high-confidence
  matches that look wrong on inspection.

## Cost estimate

- Black Vault corpus is on the order of 100k–500k pages (depends on
  archive scope). Embedding cost: ~$3–15 with Voyage-3.
- OCR cost: free with local Tesseract/Surya. Wall-clock ~24h for the
  Black Vault if Surya is the engine on the 5090.
- Storage: 100k pages × 1024 dim × 4 bytes = 400 MB for the reference
  index. On NAS, no problem.

## Out of scope (for v1)

- Real-time novelty checking on user uploads (we're not a SaaS).
- Cross-archive similarity matrices (interesting but not launch-critical).
- Automated detection of "leaked but not officially released" material.

## Open questions

- Threshold tuning — start at 0.85/0.70 and let methodology page show
  numbers from a manual spot-check of 50 random pages.
- Surfacing partial-overlap on the index page: badge per card, or only
  in the detail view?
- Whether to include leaked material (AAWSAP) in the reference corpus
  by default. Lean: include with explicit "leaked, not officially
  declassified" annotation.
