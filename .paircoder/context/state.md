# Current State

> Last updated: 2026-05-15 (late night, autonomous AFK run — /timeline shipped + alt-titles UI surface + Section 6 re-pin + omnibus reclassification + display-date-curation phases 1-3 + diff-page full plan)

## Saturday-morning pickup (2026-05-16)

**Start here.** Tonight's autonomous run was scoped to tier A + B from the "What can you knock out while I'm out?" decision. Everything shipped clean except one prod-side bug that I caught + fixed in the same run.

What's live on prod that wasn't there when you left:
- **`/timeline`** — new browse surface. Year-axis strip with 123 plotted dots + 35-card "undated" abstention bucket below. Reads `data/display_dates.json` (your 2 approvals) + the agent's 156 tentative proposals. As you do the phase-4 review, the page lights up incrementally.
- **Card-detail "ALSO CATALOGED UPSTREAM AS" section** on the 9 cards with duplicate-card-id alt-titles. Example: `/card/ea029a05470b8f4e` shows PR031/PR032/PR033 cross-references with DVIDS click-throughs.
- **Omnibus reclassification of the proposals queue** — 16 cards (FBI 62-HQ-83894 sections, Box 7 collections, 1940s Generals files, etc.) were rewritten from "agent proposed a single date" to "abstain with templated coverage-range reason." Your review queue is now 120 single-document cards + 16 confirm-abstain (~5 sec each) instead of 158 unfiltered. Estimated review time: 45-75 min instead of 1-2 h.
- **Section 6 (`13f86e95aed52840`) preserved-pin reaffirmation** logged in `data/audit-log.jsonl`. The May-12 OLD-bytes pin stays canonical; NEW upstream bytes are documented as the benign Adobe Paper Capture re-OCR pass per the May-14 finding.
- **Editorial finding** at `pursue-opsec/findings/2026-05-15-incident-date-field-shape.md` generalizing Issue #36 from "specific dates wrong" → "the field's shape is wrong for ~25% of the corpus." Issue #36 closed.

What I detected + fixed mid-run:
- The first `/timeline` deploy worked locally but rendered with **empty data on prod** because I used `node:fs.readFileSync` in the Astro frontmatter — that silently fails in the Cloudflare Pages build context. Switched to native ES imports (matching diff.astro's pattern). Verified live on prod: total 158, approved 2, abstained 35, 123 dots. Documented in commit `8703f2d`.

To resume phase-4 review:

```bash
python scripts/curate_dates_ui.py
# → opens http://localhost:5555/
```

Keyboard: `A` accept · `E` edit · `R` reject · `S` abstain · `J/→` skip. Your existing 2 entries stay (the script doesn't overwrite display_dates.json). 16 cards now propose abstention; you'll fast-confirm those (5 sec each). 120 cards still need a real decision (~30-60 sec each).

**One open editorial decision** carried over: your two already-approved entries are both omnibus files (1940s Generals Vol 1 + Vol 2). Per the new policy, they "should" be abstentions. Editorially defensible either way — you picked dates with cited evidence. Your call whether to leave them as-is or revisit them.

API spend tonight: **$0** (no agent re-runs; all changes via pattern-matching scripts + manual code).

## What Was Just Done

**2026-05-15 (late night, autonomous AFK) — /timeline scaffold + alt-titles UI + omnibus reclassification + display-date-curation phases 1-3 + diff-page full plan + Section 6 re-pin all shipped to prod.**

Six commits pushed (`311e16a..8703f2d`):
1. `08e5088` feat(display-dates): phases 1-3 — schema + writer agent + review UI
2. `f0fd915` chore(display-dates): 2 operator-approved entries from initial curation pass
3. `311e16a` feat(diff): arbitrary snapshot-pair selection + timeline + rename-aware diff
4. `cf52630` feat(curation): pre-classify omnibus-pattern proposals as abstentions
5. `aa6fd75` feat(timeline): /timeline page scaffold reading curated dates + agent proposals
6. `da847cf` feat(card-detail): surface alt-titles for duplicate-card-id cohorts
7. `9b4e974` chore(audit-log): Section 6 preserved-pin reaffirmation after May-14 event
8. `8703f2d` fix(timeline): use native ES imports for date overlay data (CF Pages build)

Tests: 487 pytest + 31 node:test passing (added 11 timeline-helpers + 20 diff-helpers).

Prod QC re-run (divona, 7 suites, 26 scenarios): **0 real failures** post-fix. Two known QC spec stalenesses remain (the VID `[NO ASSET URL]` scenario and diff scenario 3 cardinality) — both are spec-side tightening, not site bugs. Worth ~10 min when you're back.

**Operator-decision queue (updated)**:
1. ~~release-pipeline-gate~~ **shipped**
2. ~~display-date-curation phases 1-3~~ **shipped** (phase 4 = your Saturday review)
3. ~~diff-page-arbitrary-pair-selection (full plan)~~ **shipped**
4. ~~duplicate-card-ids Option 1~~ **shipped**
5. ~~Section 6 re-pin~~ **shipped (LOW item closed)**
6. **Two QC spec stalenesses** — small cleanup
7. **Video integrity in verify-assets-daily.yml** — extends the cron to walk video rows
8. **Schema extension** (two-slot `display_date_incident` + `display_date_document`) — deferred per tonight's finding; revisit once single-document curation reveals boundary cases
9. **incidents-map-clustering (`/map`)** — Tier 2 net-new geographic browse surface
10. **pursue-vision-augment** — Tier 2 Phase 2 VLM extraction

## What Was Just Done

**2026-05-15 (evening) — Tranche c9cc83fcaf43 promoted end-to-end; the May-12 HIGH-priority `release-pipeline-gate` proposal shipped; the public-side scaffolding for an autonomous-finds-pipeline landed (structural validator + CI gate).**

### Tranche c9cc83fcaf43 (accessibility metadata backfill)

158-card metadata-only tranche detected by the 30-min poll workflow at 2026-05-14 20:06 UTC. Zero byte changes. 130 cards got upstream `Image Alt Text`, 131 got DoD `Image VIRIN` identifiers (all `260508-D-D0360-NNNN`, sequential — single upstream batch). Pattern matches the prior 4a35f5596951 metadata-only tranche; not adversarial. Promoted via `pursue ingest run --tranche c9cc83fcaf43`.

Wiring:
- `CardMetadata` schema extended with `image_alt_text`, `image_virin`, `original_classification` (backward-compatible optional fields). Classification is extracted at parse time from alt-text when an explicit level keyword is present (Top Secret / Secret / Confidential / Restricted / Unclassified). 17 of 158 cards have an explicit level recorded.
- `web/src/components/GalleryIsland.tsx` prefers upstream alt-text over auto-generated when present, with the redaction-suffix preserved for screen-reader signal. Falls back to existing title-based alt when alt-text is absent.
- Card detail sidebar now renders the original classification as a badge + the VIRIN as a citable DoD identifier (DoDI 5040.02 format). Rendered on the 17 cards with explicit classification; VIRIN rendered on ~83% of cards.
- `/diff` page: 1-line fix to compare current snapshot against the most recent PRIOR snapshot (was comparing against Release 01 baseline, which made every diff look like a cumulative changelog instead of the per-tranche delta visitors expect).

### Release-pipeline-gate (May-12 HIGH item, now shipped)

Six implementation steps complete:

1. `tests/integration/test_card_page_coverage.py` — every manifest card_id has a built `dist/card/<id>/index.html`
2. `tests/integration/test_alias_destinations.py` — every alias terminal has a built page; alias chains acyclic
3. `tests/unit/test_snapshot_mirror_coverage.py` — pipeline + web snapshot dirs in sync, index.json drift-free, paired snapshots byte-equal, manifest mirror byte-equal
4. `.github/workflows/release-gate.yml` — wires all six AC into a single CI status check on PRs touching manifest / snapshot / aliases / finds paths
5. `.claude/skills/release-pipeline-gate/SKILL.md` — operator-side checklist mirroring the CI workflow for local pre-push verification
6. `pursue ingest run` now invokes `build_video_posters.py` and `build_pdf_thumbs.py` as part of the lockstep refresh (graceful-skip when local inputs are missing — so it runs in CI without harm and adds value operator-side)

This closes the bug class behind the four May-12 hot-fixes (`5e9b480`, `9b9b40d`, `076ef78`, `ffeeddd`, `93873c5`). 482 tests green; 11 of those are the new release-gate suite.

### Finds structural validator (public-side scaffolding)

Public-side surface for a future autonomous content pipeline. The validator at `pursue_index/finds_validator.py` enforces the structural minimum that every `/finds` entry — hand-written or future-bot-opened — must pass:

- Frontmatter completeness (title, summary, tags, cards, published)
- Citation density ≥3 `<Cite>` tags
- Methodology / abstention / provenance section present (matches the varied closing-frame patterns the corpus uses today: "Provenance of this entry", "Why X is in this archive", "What we're not claiming", "What the file establishes", "What to read instead", etc.)

Word count outside 800-5000 surfaces as a soft warning, not a gate failure. CLI runnable: `python -m pursue_index.finds_validator [path...]`. CI-runnable: step 5b of the release-gate workflow on every PR touching `web/src/content/finds/**`. All 21 currently-committed entries pass the gate; the two shortest entries (rhodes 759 words, whats-not-uap 683) surface word-count warnings.

The validator is intentionally bottom-of-the-stack: it doesn't enforce voice, style, or novelty. Those are upstream concerns. It catches the obvious structural failure modes before editorial review burns operator attention.

### Test suite + arch state

- 482 tests passing (467 before today's session + 11 release-gate + 4 finds-validator integration assertions across categories)
- All file-size warnings within the soft band (200 < lines < 400); no hard errors

### Updated operator-decision queue

1. **Release-pipeline-gate** (HIGH from May-12) — **SHIPPED**
2. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — still queued
3. **Re-pin Section 6 `preserved=true`** (LOW) — still queued
4. **Video integrity in `verify-assets-daily.yml` cron** — still queued (registry rows landed on 2026-05-14; cron filter still excludes them)
5. **`/diff` arbitrary-pair selector + timeline strip** (the FULL plan beyond today's 1-line fix) — still queued
6. **display-date-curation** (unblocks `/timeline`) — still queued
7. **autonomous-finds-pipeline** — public-side scaffolding **SHIPPED** today; remainder lives in the private fleet (writer agent, voice profile, novelty filter, bot account) and is not in this repo's scope

## What Was Just Done

**2026-05-14 (late afternoon) — NAS preservation tier rebuilt to mirror the public R2 layout prefix-for-prefix + 28 DVIDS-sourced video assets added to the preservation chain across all three storage tiers.**

The NAS-layout decision item queued earlier in the day is now resolved. NAS now mirrors primary R2 exactly:

- `archive/<byte_sha256>.<ext>` — content-addressed pool, immutable by construction; an `rclone sync` against the public bucket cannot overwrite a key because the filename IS the sha
- `<card_id>.<ext>` — current-pointer for PDFs/images (matches R2 root keys)
- `<dvids_video_id>.mp4` — current-pointer for videos (DVIDS video ID is the unique key since multiple cards can be paired with the same video)

Hardlinks tie the two views to the same inodes; storage cost = unique inodes only. The threat scenario from this morning's handoff (a future naive rclone overwriting OLD → NEW on the NAS) is structurally eliminated — `archive/<sha>` keys can never collide across byte versions.

**28 DVIDS videos preserved**. Mapping (`card_id` ↔ `dvids_video_id` ↔ `DOD_<asset_id>.mp4`) was recovered from the public DVIDS pages, and bytes were ingested from operator-side local copies. All 28 are now in:

- Primary R2 (`archive/<sha>.mp4`, IfNoneMatch immutable, hash-verified post-upload)
- Backup R2 (direct copy from primary, hash-verified)
- NAS (hardlinked into the same r2-mirror layout, hash-verified)

`data/asset-bytes-registry.jsonl` was extended with 28 new rows. Schema additions (backward-compatible): `source: "dvids"`, `dvids_video_id`, `dod_asset_filename`. `current_key` is omitted on video rows because videos are served via DVIDS iframe embeds on the public site, not an R2 alias. The backup-mirror script in `pursue-opsec` was updated to gracefully handle archive-only rows.

**Preservation guarantee state as of today:**

| Asset class | Archived byte versions | Storage tiers |
|---|---|---|
| PDFs / images | 200 | primary R2 + backup R2 + NAS |
| Videos (DVIDS) | 28 | primary R2 + backup R2 + NAS |
| **Total** | **228** | **3-place redundancy across the board** |

Registry rows: 230 (202 pre-existing + 28 video).

**Operator-decision queue (updated):**

1. **Release-pipeline-gate proposal** (HIGH from May-12) — still queued.
2. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — still queued.
3. **Re-pin Section 6 `preserved=true` (LOW)** — re-pin against the new sha OR affirm the old pin via audit-log.
4. **Integrate video integrity checks into the daily verify cron** — `verify-assets-daily.yml` currently only walks PDF/IMG cards (those have war.gov URLs to HEAD-check). Video rows are in the registry but the cron doesn't touch them. Closing this loop would extend the daily integrity guarantee to videos as well.

**Closed today (no longer pending):**
- NAS layout decision → resolved (above)
- Old NAS per-card_id paths cleanup → resolved (removed; content preserved via hardlinks)
- Operator-side NAS rsync recipe → doc updated to describe the new layout

> Last updated: 2026-05-14 (afternoon — 70-card event RE-CLASSIFIED as non-adversarial upstream re-OCR; preservation verified across 3 storage tiers)

## Read this first

Today's investigation overturned yesterday's classification. The
"silent redaction event" headline from the morning handoff was
**wrong**. It's not a redaction; it's an upstream re-processing pass
(Adobe Acrobat Paper Capture: re-OCR + rotation correction +
accessibility tagging). Same image content, added text layer, better
metadata. 3-place storage redundancy confirmed for OLD bytes. See
**`pursue-opsec/findings/2026-05-14-70-card-upstream-event-classification.md`**
for the full classification + preservation verification.

## What Was Just Done

**2026-05-14 (afternoon) — Deep dive on the 70-card byte event. Re-classified as benign upstream re-OCR, not adversarial redaction. All preservation guarantees verified across 3 storage tiers (primary R2, backup R2, NAS). Issues #60/#61/#62 closed.**

Investigation summary:
- **Spot-checked 8 of 70 affected cards** spanning all 4 agencies (FBI, DOW, NASA, State), full size-change distribution (-86% to +227%), and both already-Adobe-processed and previously-scan-only files. Every NEW PDF has identical signature: `Producer: Adobe Acrobat (32-bit) 26 Paper Capture Plug-in`, `Tagged: yes`, real OCR text layer, rotation-corrected. Every card has **identical page count** old vs new.
- **Sampled page renders** at 150 DPI for Section 1 page 70 (Wyly teletype) and Section 6 page 135 (Eekhout interview): pixel-level diffs are diffuse anti-aliasing artifacts (mean 3.28–6.84 / 255), no localized clusters indicating word swaps or in-place redactions. Content visually preserved.
- **OCR comparison**: Surya (our pages.json) is markedly cleaner than Adobe Paper Capture's embedded text on these teletype-style scans. "Free re-OCR via pdftotext" path rejected.
- **Preservation verified across 3 tiers:**
  - Primary R2 (immutable via IfNoneMatch): 140/140 keys present, sizes match
  - Backup R2 (separate bucket): 140/140 keys present + 5 OLD shas hash-verified (847 MB streamed)
  - NAS (`/mnt/nas/personal/pursue/pdfs/`): 70/70 affected cards hold OLD byte size, 4 hash-verified MATCH
- **Issues closed:** #60 (silent-overlay-detected → re-classified upstream re-OCR), #61 (preserved-tampered → upstream re-issue, not control-plane tampering), #62 (transient poll-failure, 5 consecutive successful runs since).

**Operator-decision items now queued (priority order):**

1. **NAS layout decision (NEW, MEDIUM)**: Current NAS layout is `pdfs/<card_id>/<filename>.pdf` — one file per card_id, no sha namespacing. OLD bytes are currently preserved on NAS only because no rsync ran post-event. A future naive sync would overwrite OLD → NEW, dropping the third copy. Two options: (a) adopt per-sha layout matching the rsync-setup recipe doc; (b) freeze a dated tar.gz of current `pdfs/` before any future sync.
2. **Release-pipeline-gate proposal (still HIGH from May-12)** — `pursue-opsec/findings/2026-05-12-release-pipeline-gate.md`, untouched.
3. **duplicate-card-ids Option 1** (alt-titles UI surface, ~1.5h) — unchanged.
4. **Re-pin Section 6 preserved=true (LOW)**: Either re-pin against the new sha (`7620094802…`) or affirm the old pin (`3df0935c…`) with an audit-log entry. Either is fine; the OLD bytes are already in 3 places.

**What did NOT happen** (vs the morning handoff's queued items):
- No public "redaction event newsletter" — the underlying premise was wrong.
- No re-OCR of the 70 cards via pdftotext — Adobe's text layer is lower quality than our Surya.
- No editorial response to the redaction — there was no redaction.
- No commits/code changes — investigation was read-only.

**2026-05-14 (mid-day) — Operator returned after 2-day quiet stretch. Discovered (via status pull) that the integrity layer captured a major upstream silent-redaction event overnight 2026-05-13/14: 70 cards' bytes silently changed at the same upstream URLs, total corpus shrank 2.34 GB → 1.10 GB (-53%). Both versions preserved in R2 + backup R2. [SUPERSEDED — see today's afternoon entry above]**

Headline metrics:
- 70 of 132 archived cards had bytes change at the same URL between 2026-05-12 (last archive run) and 2026-05-14 07:16 UTC (daily verify cron)
- Top drops: FBI 62-HQ-83894 Section 6 (371 → 61 MB, -310 MB), Box 7 Incident Summaries 1-100 (247 → 33 MB), Box 7 101-172 (243 → 29 MB), every FBI 62-HQ-83894 section reduced
- 41 of the 70 are FBI; 21 "Other" (mostly Box 7); 4 NASA; 2 State; 2 DOW

Issues filed by the integrity layer (all healthy behavior):
- #60 silent-overlay-detected — the 70-card event
- #61 preserved-tampered — Section 6's pinned sha no longer matches current-pointer (correctly raised; the upstream re-edit overwrote the bytes after our May-12 restoration pin)
- #62 poll-failure — single transient at 10:16 UTC, recovered next cycle, closeable

**The integrity layer worked exactly as designed.** Both old + new bytes preserved at content-addressed `archive/<sha>.<ext>` keys. Backup R2 mirror has both. Daily verify cron caught the change within hours of upstream's edit. This is the project's first real defense of its preservation guarantee against the threat model the operator articulated at the start.

**Operator-decision items queued** (next session priority):
1. Editorial response to the redaction — re-OCR? UI surface? public messaging?
2. Section 6 specifically — the May-12 finds entry (`fbi-1947-dallas-teletype.mdx`) cites Section 1 page 70 (Wyly teletype); Section 1 also redacted (109→30 MB); verify the cited page survives
3. Release-pipeline-gate proposal still open (HIGH from yesterday)
4. duplicate-card-ids Option 1 (alt-titles UI surface)

Full backlog ranking in last session's state.md entry below; full event detail in the handoff doc.

**2026-05-13 (overnight, second tranche ingested + deep audit clean)**

## What Was Just Done

**2026-05-13 (~04:15 UTC) — Tranche 4a35f559 ingested cleanly + deep cross-tranche byte audit CLEAN + plans dir cleaned per operator policy.**

Second-wave upstream catalog cleanup detected at 18:13 UTC (issue #57, since closed). 0 added/removed/quarantined/restored, 46 field-only changes (PDF-card title format updates: Section_5→Section_005, B4→B008, etc.). asset_urls + asset_filenames stable so card_ids preserved + NAS files untouched. First end-to-end test of the `promote_snapshot` deeper-fix patch (`ffeeddd`) on a fresh tranche — auto-mirrored cleanly to all three deploy paths.

**Deep cross-tranche byte audit (165 card_ids × 4 snapshots): CLEAN.** Registry byte_sha consistency 0 mismatches; asset_url drift 0; Section 6 restoration byte-identity reconfirmed against audit-log; field-only spot-check confirms title-format-only changes. Read-only investigation, no API budget, no upstream re-fetches. Findings at `pursue-opsec/findings/2026-05-13-deep-byte-review-4a35f559.md`.

**Plans dir cleaned (operator directive: don't retain shipped plans).** 8 shipped plans deleted (a11y, auto-poll, card-rename, curated-finds, doc-staleness, llm-cleaned-pilot, llm-cleaned-text, visual-browse-surface). Git history is the audit trail. Remaining: 8 backlog plans + 5 tranche-diff artifacts.

**2026-05-13 (~02:00 UTC) — Both autonomous-run PRs MERGED. Plus 4 hot-fix commits on main. Plus deeper-fix patch. Plus opsec proposal for a release-pipeline gate. Final staleness sweep clean.**

## What Was Just Done

**2026-05-13 (~02:00 UTC) — Both autonomous-run PRs MERGED. Plus 4 hot-fix commits on main. Plus deeper-fix patch. Plus opsec proposal for a release-pipeline gate. Final staleness sweep clean.**

**Merged tonight:**
- **PR #58** staleness-remediation (`merged 01:50 UTC`) — 31 audit findings + 2 Codex P2 nits + 3 plans marked shipped. Rebased once.
- **PR #59** accessibility-remediation (`merged 01:58 UTC`) — WCAG AA: 1 critical+28 serious+60+ moderate → 0 violations; new AtlasAccessibleBrowser; new contrast-test suite. Rebased twice (post-#58 + post-hotfixes).

**Hot-fixes on main (all symptoms of one structural gap):**
- `5e9b480` — sync `web/src/data/manifest.json` from pipeline manifest (was causing prod 404s on PR-renamed card pages)
- `9b9b40d` — root-cause patch in `promote_snapshot()` for the manifest mirror
- `d84b792` — restore 16 video posters at new card_ids + Section 6 PDF thumb
- `076ef78` — mirror tranche-65572b38 snapshot to web-side so /diff page compares correct pair
- `ffeeddd` — extend `promote_snapshot()` to also mirror snapshot + rebuild web-side index.json
- `93873c5` — final staleness sweep (3 more user-facing numerics: whats-not-uap, apollo-17, cite-this.md)

**Operator-stated structural fix (HIGH priority for next session):** `pursue-opsec/findings/2026-05-12-release-pipeline-gate.md` — proposes a deterministic CI-enforced GitHub Action + bpsai-pair skill that gates merges without confirming all deploy-side mirrors are in lockstep with the pipeline-side source-of-truth. Tonight's four hot-fixes are all the same class of bug. Concrete plan: 6 implementation steps, ~2.5-3 hours. Recommended top-of-backlog before the next tranche.

**Discovery flagged for editorial decision (not blocking):** `pursue-opsec/findings/2026-05-12-duplicate-card-ids-discovery.md` — tranche 65572b38 has 9 unique card_ids that appear multiple times because upstream reuses one PDF's `asset_url` across multiple "cards" with different titles. 12 collapsed instances. Three remediation options laid out; recommendation Option 3 (post-parse disambiguation, backward-compatible).

**Live deploy verified:** all key URLs return 200; / shows 4,161 pages; /atlas shows 4,127 dots; /diff references 65572b38.

**2026-05-12 (overnight) — WCAG 2.2 AA accessibility audit + remediation across the entire site. Branch: `accessibility-remediation`. axe-core scan: 0 violations across 18 representative routes (all pages + a representative card detail page).**

Implements `.paircoder/plans/accessibility-audit-and-remediation.md` end-to-end. Operator constraint: fix everything, defer nothing. Outcome:

- **Color contrast (WCAG 1.4.3).** `--color-text-faint` (#4a5563) was failing AA on every background (2.06–2.57:1, 152 usages). `--color-text-dim` (#6b7783) only met large-text. Bumped to `#8390a0` / `#9ba6b3` — minimum changes that hit AA on every surface while preserving the dim < faint < text < bright hierarchy. Atlas legend swatch for "UNKNOWN" updated in lockstep (`atlas-helpers.ts`). Drift guarded by new pytest `tests/unit/test_a11y_contrast.py` (38 parametrized cases + a token-table-vs-CSS sync check).
- **Skip link (WCAG 2.4.1).** `Base.astro` now ships a `.sr-only-focusable` skip-to-main link as the first focusable element on every page. Visible-on-focus, signal-green styling, 9999 z-index.
- **Atlas accessible alternative (WCAG 1.1.1 for the WebGL canvas).** New `AtlasAccessibleBrowser.tsx` companion island renders the corpus as a sortable HTML table with `aria-sort` headers, agency/date view toggle, and free-text filter. Keyboard- + screen-reader-friendly path to the same `/card/<id>` destinations the canvas dots link to. The canvas itself now carries `role="img"` + `aria-label` + `aria-describedby` pointing at an `.sr-only` long summary built from the manifest's per-agency counts.
- **Form labels.** Chat textarea now has an `<label for="chat-input">` (sr-only). Every `<select>` in `CardExplorer` is now wrapped by `<label>` + carries `aria-label` (was previously orphaned). `SearchFilterRail` uses `<fieldset>` + `<legend>` for the agency-pills group and the date-range group instead of a `<p>` "label" sibling.
- **Live regions.** Chat transcript: `role="log" aria-live="polite"`. Phase indicator (RETRIEVING/GENERATING): `role="status"`. Search results count: `aria-live="polite" aria-atomic="true"`. Atlas + search loading states: `role="status"` with sr-only "Loading…" text. Error states: `role="alert"`.
- **Heading hierarchy.** 404 page now has an `<h1>` (sr-only — the visible "shell error" block stays as decoration with `aria-hidden`). Card sidebar `<h3>`s for ASSET / CROSS-REFERENCES / OCR TEXT promoted to `<h2>` (siblings of the SOURCE h2 under the card h1). Finds-entry "Sources" promoted from `<h3>` to `<h2>`.
- **Decorative aesthetic.** Every `$ grep -ri ...` shell-prompt header is `aria-hidden="true"` (decoration; the meaningful h1 sits directly below). Top scanline div, breadcrumb `/` separators, gallery dots, atlas legend swatches all `aria-hidden`. Chat gear emoji wrapped in `aria-hidden`.
- **Nav semantics.** Primary nav has `aria-label="Primary"` and the active link carries `aria-current="page"`. Breadcrumbs on `/card/<id>` and `/finds/<slug>` have `aria-label="Breadcrumb"` + `aria-current="page"` on the leaf. GH external link has `aria-label="…(opens in new tab)"`. Per-removal-event link rows on `/removed` switched from `<nav>` to `<div>` to avoid duplicate-landmark axe violations.
- **Alt text.** Gallery image alts now include "(contains redactions)" when the underlying card is redacted, so screen readers get the same signal sighted users get from the visible REDACTED corner badge.
- **Global focus-visible ring.** Added to `global.css` for `a` / `button` / `[role="button"]` / `[role="tab"]` / `summary` so custom-styled buttons that don't define their own ring still surface focus visibly.

**Verification:**
- `cd web && npm run build` — clean, 181 pages built
- `pytest tests/unit/ -q` — 443 passed, 2 deselected
- axe-core/Puppeteer scan over 18 routes — **0 violations of any severity, including best-practice tags**
- `bpsai-pair arch check tests/unit/test_a11y_contrast.py` — clean

**Operator-decision item carried in commit message:** the `--color-text-faint` / `--color-text-dim` bumps shift two tokens used on every page. Visual diff is small (still distinctly dim) but worth a sanity-check on a few representative surfaces before merging.

Findings file lands at `pursue-opsec/findings/2026-05-12-accessibility-remediation-results.md` in the operator opsec repo.

**2026-05-12 (late evening) — Card-rename plan COMPLETE (steps 1-7). Tranche 65572b38 ingested + promoted. Surgical v1.0.0/numeric-drift fixes on the highest-traffic public surfaces. Backlog re-prioritized.**

Steps 6 + 7 of the card-rename plan landed:
- **Step 6**: `tests/unit/test_finds_citations.py` — CI test asserts every `<Cite card="...">` (and `cards:` frontmatter) in `web/src/content/finds/*.mdx` resolves via current manifest, /removed, or alias chain. 3 tests including alias-chain-acyclicity defense. **Caught one real broken citation on first run**: `fbi-62-hq-83894-section-6-removed-2026-05.mdx` cited `9c86c04b5e4a50e8` (the no-asset_url Section 6 transient mid-state from the 0d7e9ba1 tranche). Fixed by adding an operator_manual alias `9c86c04b → 13f86e95` (the canonical Section 6 card_id) to `data/card-aliases.json`. Now 17 aliases live; CI green.
- **Step 7**: `pursue ingest run` orchestrator (`src/pursue_index/ingest_run.py` + CLI) — gate-checks the tranche, locates the snapshot, promotes to `latest.json`, identifies which downstream stages need to run based on tranche-diff classifications. For 65572b38 (metadata-only): just promote + rebuild deploy mirrors via `cd web && npm run build`; no OCR/embed work needed. 9 unit tests, all green. Also added prefix-matching to the gate's sha lookup so CLI invocation with the 12-char display prefix works.

**Tranche 65572b38 ingested**: `data/manifests/latest.json` is now the new snapshot. Astro build clean: 181 pages.

**v1.0.0 / numeric-drift surgical fixes** on the highest-traffic surfaces:
- `web/src/pages/methodology.astro`: "Research preview (v1.0.0)" → "(v1.1.0)"; loosened framing
- `web/src/layouts/Base.astro`: "v1.0.0 preview" / "v1.0.0 calibration" → drop version-specific framing
- `web/src/pages/index.astro`: "4,153 PAGES" → "4,161 PAGES"
- `web/src/pages/atlas.astro`: "4,119 OCR'd pages" → "4,127"
- `README.md`: "4,153 OCR'd pages spanning the 116 PDF cards in Release 01" → loosened to avoid future drift
- `docs/architecture.md`: "161 in Release 01" → "158 in PURSUE Release 01 (as of tranche 65572b38)"
- The comprehensive 31-finding sweep is what `pursue-opsec/findings/2026-05-12-documentation-staleness-audit.md` covers — recommended as the next priority work.

**Backlog re-prioritized** (in "What's Next" below). Recommended #1: documentation staleness remediation. Already-scoped findings, low-risk, high editorial-credibility return.

**Editorial accuracy correction** that came out in this session: I had earlier characterized FBI Photo B-series and State Cable 004 as net-new content in tranche 65572b38, based on a shallow CSV diff. That was wrong. The proper card_id-based tranche_diff shows 0 net-new content in this tranche; both FBI Photos and Cables were already in the prior 0d7e9ba1 tranche with slightly different titles/URLs that the shallow diff treated as added/removed pairs. Corpus is at 158 cards in upstream + 3 on /removed = 161 unique cards = matches the original May-8 count exactly. No content lost across the entire history.

**2026-05-12 (evening) — First end-to-end tranche approval ran clean for 65572b38. Audit re-verified FBI Section 6 byte-identity; 16 PR-card renames materialized to card-aliases.json.**

`pursue ingest approve` executed against tranche 65572b38 with all 16 quarantined → operator_manual rename pairings. The pre-approval TOCTOU audit re-fetched FBI 62-HQ-83894 Section 6 from upstream (~370MB, ~10s actual runtime), confirmed byte_sha256 still matches the morning's pin (`3df0935cf48e6847d0a5df77a987f8a446e545cc1dda20cad60f79d966516568`), and emitted summary `ok: 1, skipped: 16`. Approval recorded; 16 alias rows written to `data/card-aliases.json` with operator_manual provenance; full audit row appended to `data/audit-log.jsonl`.

This is the first time the integrity stack has run end-to-end against a live upstream change with operator approval. The full chain held: poll detected the rename → byte-archive captured every byte stream → tranche-diff classified the 158 cards → side-by-side metadata review confirmed all 16 PR renames as clean → audit re-verified the restoration → approval clean → aliases materialized. The worker resolver shipped in step 2 will redirect `/card/<old_id>` for all 16 + Section 6 from the next deploy.

Open follow-up: full `pursue ingest run` (manifest promotion + OCR/embed/clean + deploy rebuild) for tranche 65572b38. Currently the deployed `latest.json` is still the prior `0d7e9ba1` snapshot; the approval clears the gate but doesn't auto-promote. Step 7 of the card-rename plan covers the orchestration.

**2026-05-12 (evening) — Post-ingest TOCTOU audit (plan step 5) shipped. `pursue ingest approve` now runs an inline pre-approval re-fetch audit; refuses approval on any sha mismatch.**

Step 5 of the card-rename plan landed. New `pursue_index.post_ingest_audit` module re-fetches upstream bytes at approval time for every byte-collision rename and every restored_unchanged event, compares against the sha recorded at tranche-diff time, and surfaces any mismatch as a blocking error before aliases are materialized. 9 unit tests, all green; arch-clean.

The audit catches the TOCTOU scenario: upstream serving bytes A during tranche-diff and bytes B during approval — turning a confirmed safe-to-alias event into a content swap done under cover of metadata change. Three target classes:

- `byte_collision_rename` (Class A) — expected_sha is from tranche-diff; refusal on mismatch
- `restored_unchanged` (Class D) — expected_sha is the pinned byte_sha from the registry; refusal on mismatch
- `operator_manual_rename` (Class C approved) — typically no asset_url (PR/VID metadata-only cards); skipped with note when no asset_url is present, sha recorded for audit trail otherwise but never refused

Wired into `pursue ingest approve` with a `--skip-audit` escape hatch for emergency cases. Audit results are appended to `data/audit-log.jsonl` for permanent provenance. The `--snapshots-dir` flag locates the candidate manifest snapshot needed to look up asset_urls.

Characterization helpers (OCR-text diff, PDF metadata diff for `restored_modified` investigation) deliberately deferred — no `restored_modified` or differing-byte Class C entries in the current tranche to warrant the build.

For the current `65572b38` ingest, the audit will re-fetch ONE card (FBI 62-HQ-83894 Section 6, ~370MB, ~30s) to verify the restoration is still byte-identical at approval time. The 16 operator_manual aliases all have null asset_urls and will be skipped automatically.

**2026-05-12 (early evening) — Ingest-approval gate (plan step 4) shipped. `pursue ingest approve` / `pursue ingest check` CLI live, integrated into the existing typer CLI.**

Step 4 of the card-rename plan landed. New `pursue_index.ingest` module with the gate primitives (`is_tranche_approved`, `record_approval`, `auto_approve_renames`, `parse_rename_flags`, `append_aliases`) and `pursue_index.cli.ingest_cli` typer wrapper exposing `pursue ingest check` and `pursue ingest approve`. 16 unit tests, all green; arch-clean.

The CLI:
- `pursue ingest check --tranche <sha>` returns exit 0 if approved, 1 if not. Downstream ingest-pipeline commands call this gate to refuse to proceed against an unapproved tranche.
- `pursue ingest approve --tranche <sha> --note "..." [--approve-rename <new>=<old>]...` records an audit-log row and materializes the approved aliases into `data/card-aliases.json`. Class A entries (byte-collision-confirmed renames) are auto-included; Class C / quarantined entries require explicit `--approve-rename` flags. The CLI surfaces a warning if any quarantined items go unaddressed (gate still clears, but those renames are NOT in aliases.json — operator must come back if/when they decide).

Approval-log infrastructure at `data/tranche-approval-log.jsonl` (append-only, JSONL, corrupt rows skipped on read). Failure-mode discipline: missing log → unapproved; corrupt rows → skip; malformed `--approve-rename` flags raise ValueError so operator notices before writing a broken alias. The `byte_collision` vs `operator_manual` method field distinguishes cryptographically-confirmed from operator-judgment renames in the audit trail.

The first real exercise of the gate against tranche `65572b38d27c` (which has 0 Class A + 16 quarantined + 1 restored_unchanged) is the operator-driven next step — pending review of the 16 quarantined.

Editorial note baked into the design: a different byte_sha means *something changed* — re-render, metadata edit, font subset shift, redaction-layer update, or genuine content edit. The integrity layer detects change; it does not characterize it. Step 5 (post-ingest tampering audit) will add characterization helpers (OCR-text diff, PDF metadata diff, page-count delta) that turn "sha changed" into "here are the specific differences, you decide." Approval-CLI messaging deliberately avoids "tampering" / "malicious" wording when surfacing `restored_modified` items.

**2026-05-12 (late afternoon) — `tranche_diff.py` (plan step 3) shipped + restoration-class detection (Class D) added on first real-world exercise.**

Step 3 of the card-rename plan landed. New `scripts/tranche_diff.py` (326 lines) + supporting helpers in `src/pursue_index/tranche.py` (heuristics, levenshtein, numeric-id extraction) and `src/pursue_index/tranche_report.py` (markdown + JSON rendering). 31 unit tests, all green; arch-clean.

Classifies every added card_id in an incoming tranche into one of six classes:
- **A** confirmed rename (byte_sha collision against existing registry entry → safe to alias)
- **B** net-new content
- **C** quarantined (no collision, but title-continuity heuristics match an old card → manual review)
- **restored_unchanged** previously-archived card_id reappears with byte-identical content (safe)
- **restored_modified** previously-archived card_id reappears with DIFFERENT bytes (possible tampering disguised as restoration — manual review)
- **restored_unknown** previously-archived card_id reappears but no asset_url to verify

The restoration class wasn't in the original plan; surfaced during first real-world exercise against the live `65572b38` tranche when FBI 62-HQ-83894 Section 6 (`13f86e95aed52840`, the card pinned to /removed earlier today) showed up in the new manifest as "added." The threat model explicitly names this scenario ("re-publication after removal as cover for content edits"), so added the detection logic + tests + report sections in the same commit.

First real-world dry-run against `65572b38` (heuristic-only, no byte-sha fetches): **0 confirmed renames, 16 quarantined, 1 restored_unknown (FBI Section 6), 17 removed, 93 field-only changes**. The 16 quarantined are PR40↔PR040-style zero-padding renames that will mostly resolve to Class A once we run with real byte fetches. The 1 restored_unknown will resolve to either `restored_unchanged` (safe — same bytes we pinned) or `restored_modified` (SUSPICIOUS — possible tampering). The 17 removed are the old-format predecessors of the quarantined renames.

**2026-05-12 (afternoon) — Three new finds entries shipped + card-rename handling plan adopted + audit-findings sensitivity-routed to opsec + worker alias resolver (plan step 2) live.**

Step 2 of the card-rename plan landed (worker alias resolver). New module `worker/aliases.js` (141 lines) loads `data/card-aliases.json` from the static-assets binding, builds an in-memory lookup map honoring append-only semantics (latest entry wins per old_card_id; `operator_revoke` removes the alias; subsequent rows re-establish). 18 unit tests + 8 integration tests (in `worker/tests/`); 108 worker tests total now pass.

Wired into `worker/index.js`: `/card/<old_id>` 301s to `/card/<new_id>` with `X-Pursue-Aliased-From` header before falling through to ASSETS; `/pdf/<old_id>.pdf` continues to serve preserved bytes from R2 at the old key and stamps `X-Pursue-Aliased-To` header (preservation contract — never redirect PDFs, always serve at the original handle and signal the new identity via header). Failure-soft: a corrupt/missing aliases file silently yields an empty index, never affecting non-aliased requests.

Initial empty aliases file (`{"aliases": []}`) deployed at `data/card-aliases.json` (source) and `web/public/data/card-aliases.json` (bundled into Astro build). Worker is deployable today with the empty file — does nothing until tranche_diff (plan step 3) starts writing alias rows. Astro build clean: 181 pages.

Editorial side-effect: caught a YAML quoting bug in the new Apollo 11 finds entry (`1969` unquoted parsed as int, breaking the content-collection schema). Fixed alongside this commit.

**2026-05-12 (afternoon) — Three new finds entries shipped + card-rename handling plan adopted + audit-findings sensitivity-routed to opsec.**

Three curated finds entries written and editorially approved, document-first (no external-narrative framing): `fbi-1947-dallas-teletype.mdx` (Wyly+Hottel disambiguation in FBI 62-HQ-83894), `fbi-usper-2025-orb.mdx` (modern FD-302 vs MISREP grammar contrast), `apollo-11-debriefing.mdx` (the in-conversation reasoning arc on three distinct anomalies, with cosmic-ray-flashes as the document's strongest physical-science moment). Earlier-draft rebuttal framing scrubbed.

**Card-rename handling plan landed** at `.paircoder/plans/card-rename-handling.md`. Codifies the three-class trust hierarchy (confirmed rename via byte_sha collision / net-new content / suspicious replacement quarantined). Critically distinguishes the always-on capture layer (poll + byte-archive + tranche-diff + daily verify, all unattended-safe) from the operator-gated editorial-publication layer (`pursue ingest run` with tranche-approval). All four open questions resolved: (1) always quarantine Class C, no auto-approval rule; (2) old card_ids preserved forever via append-only aliases — codified as a contract section; (3) bandwidth acceptable; (4) per-card pill on detail page, no new nav surface.

**Documentation-staleness audit findings (31 items) moved** to `pursue-opsec-staging/findings/2026-05-12-documentation-staleness-audit.md`. Audit plan itself stays public (describes the approach, not the current weaknesses). General policy adopted: plans describing how the system works → public; audit findings revealing current weaknesses → opsec until remediated.

**2026-05-12 (mid-day) — Closed the /removed integrity gap + caught the upstream CSV rename + tier-1 backup mirror first-sync verified.**

Operator-driven session: started from the question "where did the May 8 R2 uploads go and are all bytes accounted for?" Built a read-only reconciler (`scripts/r2_reconcile.py`) that diffed the R2 bucket against the asset-bytes-registry. Found exactly **3 orphan objects** — all corresponding to the 3 cards on `/removed` (FBI Section 6, DOW-UAP-D20, NASC-State). These had been uploaded May 8 as part of PR #27's bulk-load and were never brought under the integrity-layer's coverage when the byte-archive stack landed overnight May 11→12.

Closed the gap:

- **`scripts/r2_pin_removed.py`** (with TDD: 6 unit tests, mock-S3-client). Walks `removed-cards.json`; for each card: HEADs R2 → GETs current-pointer bytes → computes byte_sha256 → PUTs to `archive/<sha>.<ext>` with `IfNoneMatch: "*"` (append-only) → appends a registry row with `preserved: true`. Idempotent. Live run pinned 2 archive entries (D20, FBI Section 6) and reported `archive-existed` for the State memo (see byte-finding below).
- **`scripts/r2_verify_preserved.py`** (with TDD: 5 unit tests). Companion to the manifest-walking verify cron — re-reads each preserved card's bytes from R2 and compares against the pinned byte_sha. Different threat model from silent-overlay-detected: this catches in-control-plane tampering (leaked write key, buggy script, accidental wrangler PUT).
- **`.github/workflows/verify-assets-daily.yml`** extended with a new `verify-preserved` step + new `preserved-tampered` issue label/title with full sha-diff body when a preservation copy mismatches.

**Editorial finding surfaced by the integrity layer itself.** The pin's IfNoneMatch returned `PreconditionFailed` on the NASC-State card (`aa3097b4c549a67a`): the archive key already existed because **current-manifest card `9e2c2621d67dde12` has byte-identical content**. Same pattern as yesterday's D20 refutation. The "1963 → 1952 file-swap" framing was incomplete: upstream's 2026-05-11 change to that listing was actually **two operations at once** — (a) re-issued the same 1963 NASC memo at a corrected 1963-coded title (byte-identical, cryptographically verified), and (b) added a genuinely-new 1952 State memo at the original 1952-coded title. The 1963 content was preserved verbatim across the rename. Finds entry `nasc-state-extraterrestrial-policy-memo-1963.mdx` updated with a new "Byte-level integrity finding" section, a corrected preservation table (now 3 cards), and a sentence in provenance about how the tooling discovered the identity.

**Tier-1 durability mirror verified.** Manually triggered `mirror-to-backup-r2` workflow in `pursue-opsec` after operator set the 7 backup R2 secrets. First sync: **129 archive_copied + 129 current_copied, 0 failures, ~13 minutes for ~6 GB.** Tier-1 cross-account redundancy is now live. The 3 newly-pinned preserved entries weren't in this sync (they were uncommitted at trigger time) — re-trigger queued for after this commit pushes.

**Upstream CSV rename caught and patched.** During the session, the operator noticed three consecutive poll-workflow failures (15:28, 16:20, 17:15 UTC) and asked. Investigation: war.gov restructured the UAP site and renamed `uap-csv.csv` → `uap-release001.csv`. The old URL now 404s; the new URL is linked from `war.gov/UFO/` and serves the same 158-card content with the same shape. The naming pattern (`release001`) strongly suggests upstream is moving to **explicit release versioning** instead of mutating a single canonical CSV — actually a *better* upstream model. One-line fix to `csv_url` default in `src/pursue_index/config/settings.py`; 35 existing CSV/poll tests still green. Auto-filed `tranche-poll-failure` issue #55 will close on the next successful poll tick after push.

**Reconciliation final state**: 0 orphans, 0 missing, 263 R2 objects all accounted for by 132 registry rows (3 of which are preserved entries; 1 archive key is shared between aa3097b4 and 9e2c2621 because their bytes are identical).

**2026-05-12 (overnight, ran through morning) — Archive integrity stack + /gallery complete + repo cleanup + reviewer cycle + OPSEC hardening + replacement-card pipeline + VID playback.**

The session ran from sunset through to ~1 AM operator-time the next day. Headline: v1.1.0 shipped at the midpoint; second half was reviewer cycle, security hardening, operator-private companion repo (`pursue-opsec`), tier-1 durability infrastructure, and the catch-everything-at-the-end items the operator surfaced (VID playback was a real bedtime blocker; OCR-deployment drift was a real subtle gap that none of the green-checkmark workflows caught).

Late-session additions on top of the v1.1.0 release notes:

- **`pursue-opsec` private companion repo created (`BPSAI/pursue-opsec`)** with README + findings/2026-05-12-reviewer-cycle.md + reference/{thresholds,trust-boundaries,data-schemas,nas-rsync-setup,r2-destructive-edit-test}.md. SECURITY.md on the public repo got a new "Internal disclosure policy" section codifying that security findings go private, never public issues. Four reviewer-cycle public issues deleted retroactively (#49 patched + closed by commit, #50/#51/#52 deleted from public, content preserved in pursue-opsec).
- **OPSEC hardening on the public repo**: branch protection on `main` (force-push + deletion blocked, enforce_admins=false so bot can still push), wiki + projects disabled, R2 archive PUTs now use `IfNoneMatch: "*"` for atomic immutability. Public forks couldn't be disabled (GitHub policy on public repos). `pursue-opsec` got branch protection + forks-off + wiki/projects-off as belt-and-suspenders.
- **Tier-1 durability** wired in `pursue-opsec`: `mirror_to_backup.py` + workflow that mirrors `pursue-pdfs` → a backup R2 bucket (different account preferred) on a daily 08:13 UTC cron. Hash-pinned boto3 via `requirements-mirror.txt`. Graceful-exit on missing creds. Operator-side NAS rsync recipe at `reference/nas-rsync-setup.md` (rclone config + cron template + quarterly encrypted-snapshot recipe). Tier-2 cryptographic signing of registry rows filed as RFC issue `pursue-opsec#1` for discussion.
- **VID playback fixed** (`70e51f5`). All 28 VID cards have `asset_url: null` (DVIDS-hosted), so the card detail page was hitting `[NO ASSET URL]` for every video. Added `isVideo` branch that renders a `https://www.dvidshub.net/video/embed/<id>` iframe with "Open on DVIDS ↗" fallback. CSP `frame-src` extended to allow DVIDS. Mobile playback via the DVIDS player works post-deploy.
- **Replacement-card pipeline completed** (`4959ff3`). When OCR auto-ran for the new D20 + State memo replacement cards on the 11th, the per-card NAS outputs landed correctly but the deployed mirrors (pages.json, pages-cleaned.json, embed_index.json, embeddings.bin, atlas-layout.json) were never rebuilt — operator caught this when noticing the D20 finds entry's "OCR pending" placeholder. Ran `pursue clean run` on the 2 new cards (~$0.02 Anthropic spend), rebuilt all five deployed mirrors. **Empirical editorial finding from the side-by-side**: the "tradecraft scrub" hypothesis on D20 is REFUTED — original and replacement both carry the same sensitive markers (77 EFS, OEPS, AIM-120, ALR-56M, ALQ-184, ALE-50, HTS-P, SY0730 software-load IDs, "PRIOR SORTIES" line). The replacement is a filename/title alignment fix, not a re-redaction. Finds entry updated to document the refutation explicitly as editorial discipline. State memo replacement OCR'd to reveal a 1952 Samford-to-Nitze flying-saucer briefing memo — genuinely interesting historical content; finds entry expanded with citations.
- **Two API key leaks (mine, not the operator's)** during shell-expansion mishaps earlier in the session — ANTHROPIC_API_KEY + VOYAGE_API_KEY + PURSUE_CF_API_TOKEN all rotated by the operator. Verified-safe `[ -n "$VAR" ]` bracket pattern is now the only env-existence check pattern used.

**2026-05-12 (overnight) — Archive integrity stack shipped + /gallery complete + repo cleanup.**

- **CSV byte preservation + 30-min cadence (`a88fd18`).** Every poll now writes `data/raw/csv/<sha>.csv` content-addressed, idempotent. Bumped cron `0 */6 * *` → `*/30 * * * *`. Closes the f07601eb-tranche-lost gap. 22 poll tests + 3 new TDD tests for byte-archive contract pass.
- **R2 content-addressed asset archive (`7cd9708`).** `scripts/r2_archive_assets.py` runs on detected CSV change. HEAD-then-GET pre-flight skips unchanged assets cheaply; uploads to `archive/<byte_sha256>.<ext>` (append-only, never overwrites) AND `<card_id>.<ext>` (current pointer, what worker/pdf.js serves). Defeats the same-URL-different-bytes overlay attack.
- **Daily byte-verify cron (`9bd924d`).** `.github/workflows/verify-assets-daily.yml` — 06:00 UTC, same script, catches silent same-URL-different-bytes swaps the CSV poll cannot. Auto-opens `silent-overlay-detected` issue with dedup guard if any new row lands.
- **R2 archive baselined (`3edb5d3`).** First full pass tonight: 129/129 eligible cards have a registry row. 0 failures. The daily verify cron now has a real baseline to diff against.
- **/removed surface (`ef00c85`) + 3 finds writeups (`2970f56`).** First captured upstream removal event: FBI 62-HQ-83894 Section 6 (PDF link set to "N/A" upstream), the NASC-State 1963 file-swap (a different 1952 file now lives at that title pattern), and DOW-UAP-D20 (replaced with new card at same title, different filename). All three preserved in our archive. Hanawalt cobalt-ray finds entry also shipped (`4057a29`).
- **/gallery Phase 1 + 2 (`4c92367`, `d622431`, `17b847e`).** Image + video tile browse with type filters and year buckets. Video tiles use real poster frames extracted from operator-downloaded DVIDS .mp4s (25 of 28 unique card_ids; remaining 3 are card_id collisions from PR-series videos sharing parent MISREPs). PDF tiles use page-1 WebP thumbnails (115 of 116; one card has upstream `asset_url: N/A`). ~3.1 MB total static assets, well under CF Workers Static Assets ceilings.
- **Two Codex P2 fixes (`f94a00b`).** Issues #38 (`build_pages_cleaned.py` missing-page → skip+log) and #39 (`select_pilot_cards.py` backfill round-robin). Closed.
- **Methodology disclosure (`a0d3af3`).** Full-corpus skip rate (0.55%, 23 of 4153 pages), per-skip-reason breakdown, interpretive-cleanup boundary made explicit (1.48 → 1.4a allowed; redaction fill-in never).
- **Incident-date audit (`2b9964d`).** Systematic findings for issue #36 at `data/incident-date-audit.md`. Scraper not at fault — upstream CSV is the source. Editorial rule: prefer in-body MISREP DTG over manifest `incident_date` for /finds entries. Per-card OCR-pass follow-ups for D27 + 6 N/A cards remain.
- **Plug-the-leak hygiene.** After two accidental secret leaks (rotated both API keys + CF API token), all env existence checks now use the `[ -n "$VAR" ]` bracket pattern. Verified safe.

Tonight's commit run on `main`: 24 commits from `0035f3f` (pre-overnight) to current HEAD. All deploys live or propagating.

**2026-05-11 (evening) — Regression bug hunt + tranche f07601eb ingest + integrity ask landed.**

- **PDF iframe sandbox regression fixed (#48 — direct to main, `4e03a1d`).** Chrome 147 PDFium changed behavior: any `<iframe sandbox=...>` now suppresses inline PDF rendering regardless of allow-* tokens. Every card detail page on desktop Chrome was shipping a blank iframe; mobile masked it (system PDF viewers). Trust basis for dropping sandbox: post-PR #27 the iframe loads only same-origin `/pdf/<card_id>.pdf` from our R2 mirror, not adversarial content. CSP `frame-ancestors 'self'` + `X-Frame-Options: SAMEORIGIN` + worker card_id regex validation provide defense-in-depth.
- **Security bundle (`b6dba3f`).** HSTS header `max-age=31536000; includeSubDomains` (preload deliberately omitted) + RFC 9116 `/.well-known/security.txt` per operator audit. Clears 3 of the 11 audit items; DMARC + Always-Use-HTTPS + AI-bot toggles are operator dashboard/DNS actions.
- **Reader/Cleaned pagination regression fixed in two passes (`6d41ac6` then `ed93bb0`).** Operator-reported "first click works, then stuck" across both Reader and Cleaned modes, desktop + mobile. Reproduced live: rapid clicks within a single tick batched correctly (state 1→5), but sequential clicks with any wait failed after the first. The first-pass useReducer fix did not clear it on prod. Second pass refactored to ref-driven `navigateTo(target)`: handlers read `activePageRef.current` + `totalRef.current` live, compute the explicit target page, dispatch a `set` action, and do `history.replaceState` + iframe sync inline in the same call. Eliminates the deferred-useEffect race that was the root cause.
- **Mobile title overflow fixed (`e0d7add`).** `break-words` on the card title h1 so long technical filenames wrap on narrow viewports.
- **Augment loader hardened (`d60d9d9`).** Four corrupt rows (lines 448–451) in `alex-zhang42-corpus.jsonl` were aborting the entire embed. Parser now skips per-row with a logged sample and a 5% wholesale-corruption guardrail.
- **Cleaned-mode fetch race fixed (`e5defd7`).** The pre-existing "sometimes loads, sometimes doesn't — refresh fixes it" hang: useEffect dep `cleanedStatus` caused the fetch effect to re-fire on every status transition (idle → loading → loaded), racing with the 7.7 MB `r.json()` parse and stranding state on "loading." Gated via `useRef` flag; deps shrink to `[mode, base]`; cleanup-cancellation on unmount/mode-switch.
- **Tranche f07601eb ingested.** Scrape → 158 cards (was 119; +39: 28 VIDs + 14 IMGs + 0 net new PDFs). Download → 129/158 (the 29 missing are DVID-hosted videos; `PURSUE_DOWNLOAD_VIDEOS` default off). OCR → 116 PDF cards (no new pages). Embed → 1216 new embeddings, 2911 skipped, 418,704 tokens, **~$0.025**. Then re-run with augment-from: 1132 pages got VLM image tags (lenient parser caught the 4 corrupt rows).
- **API key rotation.** Operator rotated `ANTHROPIC_API_KEY` + `VOYAGE_API_KEY` after the assistant accidentally printed both via a misused `${VAR:-default}` bash expansion. New keys deployed to `.env` (local) and CF Worker secrets (live via `npx wrangler secret put`). No GitHub Actions reference either key.

**2026-05-11 — Fact-check pass + LLM-cleaned pilot resume.**

- A r/UFOs reader DM'd the operator pointing out that the Muroc-1947 entry stated Roswell was "2,000 miles east" of Muroc/Edwards AFB. Actual great-circle distance is ~800 mi. Fixed directly on `main` as `5c8a0a9`.
- Defensive fact-check pass across all 14 `/finds` entries (via Explore agent). Verified Apollo 17, Kenneth Arnold, LaPaz fireballs, Mantell, Rhodes Phoenix, FBI 62-HQ-83894 sectioning, LaPaz/Institute of Meteoritics. **No additional factual errors.**
- One HIGH-severity ambiguity surfaced and fixed: D23 entry's manifest `incident_date: 10/31/2023` vs MISREP Zulu DTGs (Oct 24, 2023). In-entry clarifier landed as `d7258e9`. Manifest-field correction continues as Issue #36.
- LLM-cleaned pilot resume kicked off: `pursue clean run --cards <30> --budget-usd 0.75`. PR #46's content-filter graceful-skip validated in production (page 93 of card `7d58f0cac741650a`). Pilot hit the cap at 3 cards; extension pilot on 3 modern MISREPs (D23/D32/D33) added at $0.08, zero skips. Combined pilot output: 385 cleaned pages + 88 skip rows across 6 cards for $0.83.
- Spot-check checklist for the pilot output landed at `.paircoder/plans/llm-cleaned-pilot-spotcheck.md` — 40 checks across 5 pages, ship-readiness criteria explicit. Manual spot-check executed; **0 hard signals + 1 soft signal across 5 pages → GO verdict**. Lone soft signal: D33 p1 `1.48 → 1.4a` interpretive cleanup (single-character OCR fix in context, defensible but worth documenting in methodology).
- Full corpus pass launched: `pursue clean run --budget-usd 25.00`. Running in background; projected $8–12 spend across ~4,153 pages.
- QC engine plan landed: `.paircoder/plans/clean-quality-review.md` — LLM-judge layer over the cleanup output, ~$6 (Haiku judge) or ~$42 (Sonnet judge) per corpus pass, with explicit calibration discipline (20-page operator sample per run).

**2026-05-10 — v1.0.0 shipping run (19 PRs merged).**

- v1.0.0 tag + GitHub release shipped against PURSUE Release 01.
- 14 finds entries live (was 11): added D32 (#32), D23 (#34), D33 (#35).
- LLM-cleaned reading text overlay shipped as **dark code** (#37): pipeline + CLI + UI toggle live, `pages-cleaned.json` not yet produced. Toggle reads "Cleaned text not yet available for this card." Full corpus run is the gate to flip live (pilot in progress, see above).
- Content-filter graceful-skip (#46): runner no longer crashes on Anthropic moderation rejections; writes a `content_filter` skip row and continues.
- Self-hosted PDFs via Cloudflare R2 (#27) — fixes war.gov framing-block iframe issue.
- Atlas regl-scatterplot fixes (#25, #26, #30, #31): CSP unsafe-eval, UMAP [-1,1] normalization, colorBy/opacityBy lookup-array config, mobile cluster fallback retired.
- Search title-match highlight + dropped fuzzy expansion (#29).
- alex-zhang42 augmented retrieval elevated to project differentiator (#41); `/methodology` deep-links to OCR benchmark (#42).
- Repo audit cleanup: redactions + housekeeping (#44), accessibility audit + remediation plan (#45), pursue-vision-augment Phase 2 plan (#43), CI tightening (#22, #23, #24, #28), agent-memory untracked from public repo (#21 era).

## Known dark code

| Feature | Implementation | Wiring | Validation | Output | Live? |
|---|---|---|---|---|---|

No dark code currently. The LLM-cleaned reading text shipped fully on 2026-05-11 (PR #37 + #46 + `0035f3f` for the asset + post-deploy pagination/race fixes). The dark-code row from earlier in the day cleared with `0035f3f`; subsequent fixes were live-bug regression patches, not unwired features.

## Current Focus

Public site live at <https://pursueindex.com>. Full pipeline (scrape →
download → OCR → embed → serve) shipped end-to-end against PURSUE
Release 01. Chat interface live with mandatory `[card_id:page]`
citation discipline and abstention behavior. Repository is public
(`BPSAI/pursue-index`, Apache-2.0).

A complementary CC0 dataset (`alex-zhang42/ufo-pursue-open-atlas`)
released for the same source with VLM-described image content; we
credit it on `/methodology` under Related Work and ingest its
image-description blocks into our retrieval index.

## Active Plan

| Stage     | Status   | Output                                                             |
|-----------|----------|--------------------------------------------------------------------|
| scrape    | shipped  | curl_cffi + Chrome TLS, 161-card manifest, hash-pinned             |
| download  | shipped  | 116 PDFs + 14 images on NAS via content-addressable layout         |
| ocr       | shipped  | 3,529 Surya pages + 624 LLM-cleaned pages (auto-mode), 4,153 total |
| embed     | shipped  | Voyage-3 1024d float16, ~8 MB in-browser payload (1,208 augmented) |
| serve     | shipped  | Astro static + CF Worker (CORS-locked, 5/IP/24h, $100/day cap)     |
| chat      | shipped  | RAG with mandatory citations, anonymous + BYOK tiers               |
| novelty   | shipped  | machinery + UI; placeholder reference corpus (10 passages)         |
| atlas     | shipped  | 2D UMAP semantic browser at `/atlas` (4,119 dots, regl-scatterplot) |

## What's Live

- Custom domain at `pursueindex.com` on Cloudflare Workers + Static Assets.
- Full-text + semantic search across 4,153 OCR'd pages (MiniSearch lexical + Voyage-3 embeddings, both browser-side).
- OCR pipeline: Surya (GPU, transformer-based) primary + Anthropic vision LLM fallback for low-confidence pages.
- RAG chat with mandatory citations: anonymous tier (server-funded, 5/IP/24h, $100/day budget cap) and BYOK tier (browser-direct to Anthropic).
- Faceted search filters on `/search` (agency, incident date, redacted-only).
- Per-entry OG image cards for `/finds/<slug>` social sharing.
- Reader-mode toggle on card detail pages with `j`/`k` page navigation; iframed PDF stays in sync via `#page=N` deep linking.
- `/atlas` semantic browser: clickable UMAP projection of all 4,119 page embeddings, MiniSearch-backed search highlight, mobile cluster-list fallback.
- Public API documentation at `/api`.
- Auto-poll for new tranches: GitHub Actions cron every 6 hours fetches the upstream CSV, hashes it, opens an issue on change or fetch failure.
- Tranche diff page surfaces per-card deltas when the upstream CSV changes.
- Curated `/finds` reading guides (14 entries; added D32, D23, D33 in the 2026-05-10 run).
- Novelty detection scaffold with a synthetic placeholder reference corpus (10 passages); Black Vault integration on the backlog.
- PDF hosting self-managed from Cloudflare R2 (was war.gov direct iframe; broken by upstream framing-block mid-build).
- alex-zhang42 CC0 augmented-retrieval dataset surfaced as project differentiator on `/methodology` and in `/api/retrieve` responses (1,208 augmented chunks in the embedding index).

## Build and Deploy

- **Primary:** Cloudflare Workers Builds, configured via the dashboard. Triggers on push to `main`. Build: `cd web && npm install && npm run build`. Deploy: `npx wrangler deploy`.
- **Manual fallback:** `.github/workflows/deploy-cf.yml` runs the same chain via GitHub Actions on `workflow_dispatch`. Available as a button if Workers Builds stalls.
- **Local:** `npx wrangler deploy` from a clean checkout. Requires `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in env (or `wrangler login`).

## What's Next

### Active

_Nothing currently in flight. Tranche 65572b38 fully approved and ingested-promoted; card-rename plan complete (steps 1-7 + 1 historical alias). Section 6 finds entry could optionally be updated with a "restored 2026-05-12 — byte-verified" section (small editorial follow-up, parallel to the NASC-State pattern from this morning)._

### Recommended next priorities

**1. Documentation staleness remediation (HIGHEST RECOMMENDED).** Already-scoped: 31 specific findings catalogued in `pursue-opsec/findings/2026-05-12-documentation-staleness-audit.md`. Three drift classes: tool/engine names (Tesseract→Surya hedges), numeric facts (page counts, embed counts, etc. — surgical fixes done tonight on `index.astro`+`atlas.astro`+`README.md`+`docs/architecture.md`, but most surfaces remain), and architectural claims that haven't caught up to the integrity stack + /gallery + /removed work shipped in v1.1.0. Low-risk (no API budget, no infrastructure changes), high editorial-credibility return, scoped work. Operator-attended ~2-3 hours or one focused agent dispatch + operator review of the patch set.

**2. Accessibility audit + remediation.** Plan: `.paircoder/plans/accessibility-audit-and-remediation.md`. Priority HIGH per the plan; civic responsibility for a public archive. Includes the regl-scatterplot a11y challenges on `/atlas`. No deps.

**3. Black Vault reference corpus.** Plan: `.paircoder/plans/black-vault-reference.md`. Replaces the placeholder synthetic novelty corpus (10 hand-crafted passages) with a real FOIA prior-disclosure archive. Makes the novelty detection feature meaningful rather than illustrative. Medium priority; depends on existing novelty-detection scaffold (already shipped).

### Other backlog (in current order)

- **`pursue-vision-augment` Phase 2** — our own VLM pass alongside alex-zhang42 augmented retrieval, with per-page provenance distinguishing the two sources. Plan: `.paircoder/plans/pursue-vision-augment.md`.
- **Curated finds expansion** — 17 entries now set the editorial bar (3 new today: 1947 Wyly teletype, 2025 USPER orb, Apollo 11 debriefing); corpus has more strong candidates. Plan: `.paircoder/plans/curated-finds.md`.
- **`clean-quality-review`** — LLM-judge layer over cleanup output. Pilots when capacity opens up. Plan: `.paircoder/plans/clean-quality-review.md`.
- **Incidents map clustering** — geographic density visualization. Plan: `.paircoder/plans/incidents-map-clustering.md`.
- **Display-date curation** — UI improvement. Plan: `.paircoder/plans/display-date-curation.md`.
- **Review-and-correct pipeline** — accept community OCR transcript corrections via GitHub issues. Plan: `.paircoder/plans/review-correct.md`.
- **Autonomous finds pipeline** — auto-draft finds entries from new tranches, operator-gated for editorial publish. Plan: `.paircoder/plans/autonomous-finds-pipeline.md`.

### Open issues

- **#36** — Manifest `incident_date` audit across modern D## entries. Low priority.
- **#56** — Tranche 65572b38 detected (auto-filed by poll). **Resolved by tonight's ingest run; can be closed.**

### pursue-opsec follow-ups

- **pursue-opsec#1** — RFC: tier-2 cryptographic signing of registry rows. Awaiting operator decision on key-handling option (4 options laid out).
7. **Autonomous finds pipeline.** Background drafting of finds entries from new tranches, operator-gated for editorial publish. Plan: `.paircoder/plans/autonomous-finds-pipeline.md`.

### Open issues

- **#36** — Manifest `incident_date` audit across modern D## entries. In-entry clarifier for D23 landed 2026-05-11 (`d7258e9`); manifest-field correction still pending. Priority: Low.

## Reproducibility

The corpus pipeline is fully scripted and idempotent. From a clean
clone with the upstream CSV available:

```bash
pursue scrape run                                        # writes manifests/latest.json + archives raw CSV
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json
```

Each stage is content-addressed by `card_id = sha256(asset_url || title)[:16]`,
so partial reruns converge on the same final state regardless of order.
The manifest carries `csv_sha256` so upstream changes are detectable
in O(bytes-of-CSV).

## Quick Commands

```bash
# Pipeline (idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json --augment-from data/external/alex-zhang42-corpus.jsonl

# Tests
pytest -x                      # python
npm --prefix worker test       # worker
cd web && npm run build        # web (~169 pages)

# Web dev
cd web && npm run dev          # localhost:4321

# Worker dev (against real KV + secrets)
npx wrangler dev
```

## Blockers

None.
