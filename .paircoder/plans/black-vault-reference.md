---
id: black-vault-reference
type: feature
status: backlog
created: 2026-05-09
priority: medium
depends_on: [novelty-detection]
---

# Black Vault Reference Corpus

## Recommendation

**REFINE-FIRST → LAUNCH after written permission from Greenewald.**
The site's robots.txt explicitly allows ClaudeBot/GPTBot/anthropic-ai with `Allow: /`,
publishes structured sitemaps totalling ~92k unique PDF URLs, and the underlying
content is U.S. government FOIA releases (17 USC §105 — public domain). The technical
posture is "go". The legal posture is "almost go": there is **no published Terms of
Service or reuse policy** on the site, and Greenewald's value-add (article wrappers,
collection curation, and any OCR he produces) is plausibly his own work. We should
mail `john@theblackvault.com` (form on /documentarchive/contact/) before bulk fetch.

## What the Surface Actually Looks Like

The Black Vault is two stacked WordPress sites plus a static-host PDF library:

| Surface | Role | Scale |
|---|---|---|
| `/documentarchive/` (WP) | Article-style FOIA writeups, one per release | 1,909 posts |
| `/casefiles/` (WP) | Sighting case index + curated collections | 741 posts |
| `documents.theblackvault.com/sitemap{1,2,3}.txt` + `sitemap-www-documents.txt` | Static PDF library | ~92,479 unique PDFs |
| WP REST API (`wp-json/wp/v2/`) | Posts, media, categories with pagination + counts | Open, no auth |
| Sitemaps (XML + flat .txt) | Stable discovery surface | Updated daily |

UFO-relevant subset: WP category `ufo-phenomena` (id 32) has **377** articles;
`the-fringe` (Mysteries, id 8) has 423; on the static side, `/documents/ufos/*.pdf`
yields **~574** explicit UFO PDFs, with adjacent collections (CIA, NSA, NRO, DIA,
Project Blue Book desks, Stanton Friedman, Henry McKay, Phyllis Budinger, Philip
Mantle, Matthew Riot) adding several hundred more. **A defensible UFO+UAP-tagged
corpus is in the low thousands of PDFs, not millions.**

## Corpus Size + Cost (Order of Magnitude)

PDF size sample (5 random `/documents/ufos/*.pdf`): 58 KB / 253 KB / 833 KB / 3.9 MB
/ 14.3 MB → mean ≈ 3.5 MB. Assuming ~30 pp/MB for FOIA scans, a **3,000-PDF UFO+
adjacent-collection cut ≈ ~10–15k MB ≈ ~300k–450k pages.** A maximalist "everything
UFO-adjacent including CIA/NSA collections" cut is roughly 5,000 PDFs, ~700k pages.

Cost at our current rates:
- **Embed (Voyage-3 @ $0.13 / 4k pages):** 300k pp ≈ $10; 700k pp ≈ $23.
- **OCR (Surya GPU primary, LLM fallback):** dominated by the LLM-fallback rate;
  most FOIA scans are text-on-stamp and Surya handles them. Budget assumption:
  ~$X/1000pp blended. **Operator must fill in the current per-1000-page figure
  from the Surya/Anthropic-vision benchmark before kickoff.**
- **Total bring-up (one-shot):** dominated by OCR. Order-of-magnitude **low
  hundreds of dollars** for the UFO cut, **low thousands** for the maximalist cut.
- **Storage:** ~15 GB PDFs + ~5 GB OCR text + ~1.4 GB Voyage vectors (700k×1024×4 B)
  on the NAS under `data/reference/black-vault/`. No CF asset impact.

## License Posture

**Mixed → defaults to public domain, but ask before bulk-fetching.**

- The PDFs themselves: works of the U.S. Government → 17 USC §105 → public domain.
- Greenewald's article text (the WP `posts.content`): **his copyright.** We should
  not mirror these.
- Whether the PDFs hosted at `documents.theblackvault.com` are pristine government
  scans or include Greenewald-added OCR text layers: not knowable from the surface.
  If pristine, we can re-OCR ourselves and the question is moot. If text-layered,
  reusing the layer is arguably his work-product.
- robots.txt explicitly allows ClaudeBot/anthropic-ai/GPTBot, with a comment:
  *"Allow legitimate AI/research bots for visibility & citations in AI answers —
  These often source/link back, aligning with your transparency mission."* This is
  unusually clear consent for AI training/research access. It is **not** the same as
  redistribution consent, but it is consent for read+derive.

**Recommended posture:** email John (form at `/documentarchive/contact/`) describing
exactly what we want — a one-shot fetch of `documents/ufos/**/*.pdf` plus a small
adjacent set, fed through our own OCR, used to compute embedding-space novelty
distances for cards on pursueindex.com — with citation linkback to theblackvault.com
in /methodology and /cite. Two paragraphs, attaches the live novelty mock. Wait
for written acknowledgement before kickoff.

## Integration Shape

The new index drops into existing slots cleanly. Reference embeddings already live
behind `load_reference_index(ref_dir, archive_id)` (`src/pursue_index/novelty/compare.py:67`)
and `compute_novelty(...)` accepts an arbitrary `reference_embed_dir` and `archive_id`
(`src/pursue_index/novelty/pipeline.py:128`). The Black Vault corpus becomes
`data/reference/black-vault/{embeddings/voyage-3/{vectors.bin,index.json}, passages.json}`
— same shape as the synthetic placeholder. **No code changes to compare/aggregate
are required for the bring-up.**

What does change:
- A new ingest pipeline (sitemap → curl → manifest → existing OCR → existing embed),
  reusing the manifest/CAS pattern from the PURSUE downloader. This is its own task.
- `aggregate.py` thresholds: current `high=0.85` / `partial=0.70` / `NOVEL_FRACTION=0.70`
  were tuned against 10 hand-picked passages. **They will need recalibration**
  against a real corpus (see Risks).
- /methodology and /cite copy updates.

## Bring-Up Phases

1. **Permission** (blocking): email Greenewald, wait for written ack.
2. **Discovery** (one-shot): consume `sitemap-www-documents.txt` + `documents.../sitemap{1,2,3}.txt`,
   filter to UFO + adjacent collections, hash each URL into a manifest. ~3k–5k PDFs.
3. **Fetch** (one-shot): existing downloader (httpx + tenacity, content-addressable),
   rate-limited to 2 req/s with a courteous user-agent identifying pursueindex.com.
4. **OCR** (one-shot): existing Surya-primary pipeline. Single largest cost line.
5. **Embed** (one-shot): existing `pursue embed run` over the OCR text, written into
   `data/reference/black-vault/embeddings/voyage-3/`.
6. **Calibrate** (one-shot, ~1 day): re-run novelty with the real index against the
   current PURSUE corpus, eyeball the score distribution, and re-pick `high` / `partial`
   so the verdicts are usefully separated. Before/after comparison documented in the
   plan PR.
7. **Steady-state**: monthly re-poll of the sitemap, diff vs manifest, fetch + OCR +
   embed only the delta. Reuses the auto-poll pattern from `auto-poll-tranches.md`.

## Storage + Delivery

NAS only. Reference vectors are build-time inputs to novelty compute; only the
per-card `novelty.json` ships to `web/public/data/`. No worker / CF-Asset implications.
This was confirmed by reading `pipeline.py:128–157` — the sidecar JSON is the only
artifact crossing the build boundary.

## Methodology + Citation

Update `web/src/pages/methodology.astro` (Provenance / Novelty section): name the
reference corpus, link `https://www.theblackvault.com/`, disclose the calibrated
thresholds, and explicitly bound the claim — "novel" means "no near match in this
reference corpus," not "first time documented anywhere." Update `web/src/pages/cite.astro`
to add a Black Vault citation block when novelty tags inform a claim.

## Failure Modes + Fallbacks

- **No Greenewald reply within ~14 days, or a "no":** do not bulk-fetch. Document
  the attempt in this plan and switch to the alternatives below. Novelty stays a
  methodology demo with the synthetic placeholder, and /methodology says so.
- **Threshold recalibration shows verdicts collapse to all-`partial`:** likely means
  Voyage-3 cosines on FOIA-style language cluster too tightly. Mitigation: switch
  the page-level metric to top-3 mean (smoother) or move to a percentile-based cut
  (top-1 sim relative to the *distribution* of nearest neighbours per card).
- **Sitemap drift:** Black Vault's sitemap is generated by All-in-One SEO; treat
  any 4xx on a previously-known URL as a content move and re-discover via the
  current sitemap. Same loop the PURSUE auto-poll uses.

## Alternatives (if Black Vault is Unviable)

- **Project Blue Book** — already digitized at `archives.gov`, ~12,000 case files,
  cleanly downloadable, no permission gate. Narrower (1947–1969) but pristine.
- **CIA CREST UFO collection** — public, FOIA-cleared, modest scope (~2,800 docs).
- **NICAP / CUFOS / MUFON** — third-party UFO archives, smaller, similar permission
  questions to Black Vault. Useful as supplements, weak as standalone.
- **Combine Blue Book + CREST + a small NICAP cut** as the "no Greenewald" path.
  Coverage is lower but legal posture is unambiguous.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Greenewald says no, or no-reply | Medium | Fall back to Blue Book + CREST |
| Threshold recalibration tanks signal-to-noise | Medium | Percentile-based cuts; document calibration |
| Bulk fetch tickles WAF / rate-limits despite robots.txt | Low | 2 req/s, identifying UA, exponential backoff |
| Black Vault link-rot for sources we cite | Low | Mirror only the CAS hash + URL pair in our manifest, never the full PDF in our deploy |

## Open Questions for Operator

1. What's the current Surya+LLM-fallback OCR cost per 1000 pages? Needed to firm
   up the bring-up dollar figure.
2. UFO-only cut, or maximalist (CIA/NSA/NRO/Blue Book/named-researcher collections)?
   Affects scope ~5×.
3. Email language: do you want to write the Greenewald ask yourself, or have me
   draft it as a follow-up planning task?
