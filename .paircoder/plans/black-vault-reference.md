---
id: black-vault-reference
type: feature
status: deferred
created: 2026-05-09
updated: 2026-05-10
priority: medium
depends_on: [novelty-detection]
---

## Outcome (2026-05-22)

Prerequisite for autonomous-finds-pipeline (also deferred). Substantial multi-week integration with WordPress + static-PDF host. The novelty-detection use case it unlocks remains valuable but isn't on the critical path for any near-term sprint. Revisit when autonomous-finds becomes a priority.


# Black Vault Reference Corpus

## Summary

Use the public UFO and Space sections of The Black Vault as the reference
corpus for novelty detection on pursueindex.com. Engage with the project
as a long-running community research resource — create an account where
required, support the project financially, and credit it prominently in
our methodology and citation surfaces. The novelty signal becomes
meaningful once a real prior-disclosure archive replaces the synthetic
ten-passage placeholder currently behind `compute_novelty(...)`.

## What the Surface Actually Looks Like

The Black Vault is two stacked WordPress sites plus a static-host PDF
library:

| Surface | Role | Scale |
|---|---|---|
| `/documentarchive/` (WP) | Article-style FOIA writeups, one per release | 1,909 posts |
| `/casefiles/` (WP) | Sighting case index + curated collections | 741 posts |
| `documents.theblackvault.com/sitemap{1,2,3}.txt` + `sitemap-www-documents.txt` | Static PDF library | ~92,479 unique PDFs |
| WP REST API (`wp-json/wp/v2/`) | Posts, media, categories with pagination + counts | Open, no auth |
| Sitemaps (XML + flat .txt) | Stable discovery surface | Updated daily |

For our purposes, the UFO and Space sections are the only relevant slice.
WP category `ufo-phenomena` (id 32) has **377** articles; `the-fringe`
(Mysteries, id 8) has 423; on the static side, `/documents/ufos/*.pdf`
yields **~574** explicit UFO PDFs, with adjacent collections (CIA, NSA,
NRO, DIA, Project Blue Book desks, Stanton Friedman, Henry McKay, Phyllis
Budinger, Philip Mantle, Matthew Riot) adding several hundred more. **A
defensible UFO+UAP-tagged corpus is in the low thousands of PDFs, not
millions.**

## Corpus Size + Cost (Order of Magnitude)

PDF size sample (5 random `/documents/ufos/*.pdf`): 58 KB / 253 KB / 833 KB
/ 3.9 MB / 14.3 MB → mean ≈ 3.5 MB. Assuming ~30 pp/MB for FOIA scans, a
**3,000-PDF UFO+adjacent-collection cut ≈ ~10–15k MB ≈ ~300k–450k pages.**
A maximalist "everything UFO-adjacent including CIA/NSA collections" cut
is roughly 5,000 PDFs, ~700k pages.

Cost at our current rates:
- **Embed (Voyage-3 @ $0.13 / 4k pages):** 300k pp ≈ $10; 700k pp ≈ $23.
- **OCR (Surya GPU primary, LLM fallback):** dominated by the LLM-fallback
  rate; most FOIA scans are text-on-stamp and Surya handles them. Budget
  assumption: ~$X/1000pp blended. **Operator must fill in the current
  per-1000-page figure from the Surya/Anthropic-vision benchmark before
  kickoff.**
- **Total bring-up (one-shot):** dominated by OCR. Order-of-magnitude
  **low hundreds of dollars** for the UFO cut, **low thousands** for the
  maximalist cut.
- **Storage:** ~15 GB PDFs + ~5 GB OCR text + ~1.4 GB Voyage vectors
  (700k×1024×4 B) on the NAS under `data/reference/black-vault/`. No CF
  asset impact.

## Engagement Posture

We treat The Black Vault as a long-running community research resource
maintained by a sole proprietor (John Greenewald Jr.) whose decades of
FOIA work make this archive possible. Our posture toward the project:

1. **Create an account where the site offers one.** Sign up for the
   member-supporter access tier that the site advertises. This is the
   normal way researchers engage with the archive.
2. **Donate to support the project.** The site solicits donations; we
   contribute at a level commensurate with our use as a reference corpus.
3. **Credit prominently.** `/methodology` names The Black Vault as the
   prior-disclosure reference corpus, links to
   `https://www.theblackvault.com/`, and explicitly bounds the novelty
   claim ("novel" means "no near match in this reference corpus," not
   "first time documented anywhere"). `/cite` adds a Black Vault
   citation block when novelty tags inform a claim. The acknowledgement
   is unmissable, not buried.
4. **Introduce ourselves.** Email John (form at
   `/documentarchive/contact/`) describing exactly what we're doing —
   a one-shot fetch of `documents/ufos/**/*.pdf` plus a small adjacent
   set, fed through our own OCR, used to compute embedding-space novelty
   distances for cards on pursueindex.com — with citation linkback to
   theblackvault.com in /methodology and /cite. Include the live
   pursueindex.com URL so he can see the work in context. Two paragraphs,
   polite, professional. We treat his response with the weight it
   deserves; if he asks us to adjust scope or fetch posture, we adjust.
5. **Respect technical signals.** The site's robots.txt explicitly
   allows ClaudeBot, GPTBot, and anthropic-ai with `Allow: /`,
   accompanied by a comment about welcoming AI/research bots that
   source-link back. We honor that explicit consent. We also honor any
   rate limits the site enforces and identify ourselves clearly via
   User-Agent ("pursueindex.com novelty-detection research bot
   (contact: ...)").
6. **Fetch courteously.** 2 req/s ceiling, exponential backoff on any
   non-2xx, single one-shot fetch followed by periodic delta polling.
   We never re-pull what we already have.

## License Posture (background)

Underlying documents in the PDF library are works of the U.S. Government
→ 17 USC §105 → public domain. Greenewald's article text (the WP
`posts.content`) is his copyright; we don't mirror that. The question
of whether OCR text layers in the hosted PDFs are pristine government
output or Greenewald-added work-product is open from the surface; if
pristine, we re-OCR ourselves and the question doesn't arise. If
text-layered, we re-OCR anyway, which keeps the layer his work-product
and not ours to redistribute.

## Integration Shape

The new index drops into existing slots cleanly. Reference embeddings
already live behind `load_reference_index(ref_dir, archive_id)`
(`src/pursue_index/novelty/compare.py:67`) and `compute_novelty(...)`
accepts an arbitrary `reference_embed_dir` and `archive_id`
(`src/pursue_index/novelty/pipeline.py:128`). The Black Vault corpus
becomes
`data/reference/black-vault/{embeddings/voyage-3/{vectors.bin,index.json}, passages.json}`
— same shape as the synthetic placeholder. **No code changes to
compare/aggregate are required for the bring-up.**

What does change:
- A new ingest pipeline (sitemap → curl → manifest → existing OCR →
  existing embed), reusing the manifest/CAS pattern from the PURSUE
  downloader. This is its own task.
- `aggregate.py` thresholds: current `high=0.85` / `partial=0.70` /
  `NOVEL_FRACTION=0.70` were tuned against 10 hand-picked passages.
  **They will need recalibration** against a real corpus (see Risks).
- /methodology and /cite copy updates.

## Bring-Up Phases

1. **Engagement and project support.** Create an account at
   theblackvault.com. Set up a recurring donation at an appropriate
   tier. Send an introduction email describing the project, the use
   case, and the citation posture. Acknowledge the response, adjust
   scope if asked.
2. **Discovery** (one-shot): consume `sitemap-www-documents.txt` +
   `documents.../sitemap{1,2,3}.txt`, filter to UFO and Space + the
   chosen adjacent collections, hash each URL into a manifest. ~3k–5k
   PDFs.
3. **Fetch** (one-shot): existing downloader (httpx + tenacity,
   content-addressable), rate-limited to 2 req/s with a courteous
   user-agent identifying pursueindex.com.
4. **OCR** (one-shot): existing Surya-primary pipeline. Single largest
   cost line.
5. **Embed** (one-shot): existing `pursue embed run` over the OCR text,
   written into `data/reference/black-vault/embeddings/voyage-3/`.
6. **Calibrate** (one-shot, ~1 day): re-run novelty with the real index
   against the current PURSUE corpus, eyeball the score distribution,
   and re-pick `high` / `partial` so the verdicts are usefully
   separated. Before/after comparison documented in the plan PR.
7. **Steady-state**: monthly re-poll of the sitemap, diff vs manifest,
   fetch + OCR + embed only the delta. Reuses the auto-poll pattern
   from `.github/workflows/poll-pursue.yml`.

## Storage + Delivery

NAS only. Reference vectors are build-time inputs to novelty compute;
only the per-card `novelty.json` ships to `web/public/data/`. No worker
/ CF-Asset implications. This was confirmed by reading `pipeline.py:128–157`
— the sidecar JSON is the only artifact crossing the build boundary.

## Methodology + Citation

Update `web/src/pages/methodology.astro` (Provenance / Novelty section):
name the reference corpus, link `https://www.theblackvault.com/`, name
John Greenewald Jr. as the project's maintainer, disclose the
calibrated thresholds, and explicitly bound the claim — "novel" means
"no near match in this reference corpus," not "first time documented
anywhere." Update `web/src/pages/cite.astro` to add a Black Vault
citation block when novelty tags inform a claim. Both surfaces include a
link to support The Black Vault directly.

## Failure Modes + Fallbacks

- **John asks us to narrow scope or pause:** we narrow or pause. The
  alternatives below stay viable for a non-Black-Vault path if he
  prefers we not use his archive in this way.
- **Threshold recalibration shows verdicts collapse to all-`partial`:**
  likely means Voyage-3 cosines on FOIA-style language cluster too
  tightly. Mitigation: switch the page-level metric to top-3 mean
  (smoother) or move to a percentile-based cut (top-1 sim relative to
  the *distribution* of nearest neighbours per card).
- **Sitemap drift:** Black Vault's sitemap is generated by All-in-One
  SEO; treat any 4xx on a previously-known URL as a content move and
  re-discover via the current sitemap. Same loop the PURSUE auto-poll
  uses.

## Alternatives

If the Black Vault path closes, viable alternative reference corpora:

- **Project Blue Book** — already digitized at `archives.gov`,
  ~12,000 case files, cleanly downloadable. Narrower (1947–1969) but
  pristine.
- **CIA CREST UFO collection** — public, FOIA-cleared, modest scope
  (~2,800 docs).
- **NICAP / CUFOS / MUFON** — third-party UFO archives, smaller,
  similar engagement posture to Black Vault. Useful as supplements,
  weak as standalone.
- **Combine Blue Book + CREST + a small NICAP cut** as the alternative
  path. Coverage is lower; engagement posture is unambiguous.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| John asks us to narrow scope or use a different posture | Medium | Adjust per his guidance; fall back to Blue Book + CREST if needed |
| Threshold recalibration tanks signal-to-noise | Medium | Percentile-based cuts; document calibration |
| Bulk fetch tickles WAF / rate-limits despite robots.txt | Low | 2 req/s, identifying UA, exponential backoff |
| Black Vault link-rot for sources we cite | Low | Mirror only the CAS hash + URL pair in our manifest, never the full PDF in our deploy |

## Open Questions for Operator

1. What's the current Surya+LLM-fallback OCR cost per 1000 pages?
   Needed to firm up the bring-up dollar figure.
2. UFO-only cut, or maximalist (CIA/NSA/NRO/Blue Book/named-researcher
   collections)? Affects scope ~5×.
3. Email language to John: do you want to write the introduction
   yourself, or have me draft it as a follow-up planning task?
4. Donation tier — operator's call.
