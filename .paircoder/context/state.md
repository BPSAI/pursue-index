# Current State

> Last updated: 2026-05-09 (post-launch — public site live, full pipeline shipped; auto-poll layer added on `feat/auto-poll-tranches`)

## Current Focus

**Public launch is done.** Site is live at <https://pursueindex.com> on
Cloudflare Workers + Static Assets. Full pipeline (scrape → download →
OCR → embed → serve) shipped and re-runnable. Chat interface live with
citation discipline and abstention behavior. Repo is public on GitHub
(`BPSAI/pursue-index`, Apache-2.0) with `existing_users` interaction
limits through 2026-11-09.

A parallel project (`alex-zhang42/ufo-pursue-open-atlas`) released
hours later with a different angle: VLM-described image content, CC0
dataset on HuggingFace + 3D atlas. Crediting it on /methodology under
Related Work; ingest of their image-description blocks into our
retrieval is on the post-launch backlog (see `What's Next`).

## Active Plan

| Stage     | Status   | Output                                                             |
|-----------|----------|--------------------------------------------------------------------|
| scrape    | shipped  | curl_cffi + Chrome TLS, 161-card manifest, hash-pinned             |
| download  | shipped  | 116 PDFs + 14 images on NAS via content-addressable layout         |
| ocr       | shipped  | 3,529 Surya pages + 624 LLM-cleaned pages (auto-mode), 4,153 total |
| embed     | shipped  | Voyage-3 1024d float16, ~8 MB in-browser payload                   |
| serve     | shipped  | Astro static + CF Worker (CORS-locked, 5/IP/24h, $100/day cap)     |
| chat      | shipped  | RAG with mandatory citations, anonymous + BYOK tiers               |
| novelty   | shipped  | machinery + UI; placeholder reference corpus (10 passages)         |
| atlas     | shipped  | 2D UMAP semantic browser (/atlas) — regl-scatterplot, 4,119 dots   |

## What Was Just Done

### Session: 2026-05-09 — PR #20 review fixes (per-entry OG follow-up)

Addressed all legitimate review findings on PR #20 from vaivora
(cross-cutting), nayru (P1/P2), laverna (LOW), and chatgpt-codex
(P2). Single follow-up commit on `feat/per-entry-og-images`.

Highlights:
- **P0 draft parity**: ``finds_frontmatter.py`` now parses ``draft``
  (default False) and the build script skips ``draft: true``,
  matching Astro's ``getCollection(... !data.draft)`` filter.
- **P1 long unspaced tokens**: ``finds_og`` hard-breaks any token
  wider than ``max_width`` by character before greedy wrap, so a
  300-char URL/hash never escapes the title box.
- **P1 glob parity**: build script now uses ``rglob`` on both
  ``*.md`` and ``*.mdx``; subdir entries get PNGs at
  ``<entry.id>.png`` (matching Astro's ``entry.id`` derivation).
- **P1 multi-card label**: multi-card entries render
  ``AGENCY · prefix · 1 of N`` so the picker is visible (covers
  fbi-62-hq-83894 with 10 cards, muroc-1947 with 2).
- **P1 prefix [:10] → [:8]**: matches the source rail's
  ``c.id.slice(0, 8)``. Regenerated all 11 PNGs; 9 shrank slightly
  (fewer chars), 2 grew (the multi-card "1 of N" suffix).
- **P1 subtitle ellipsis symmetry**: extracted
  ``_truncate_with_ellipsis``; ``/FINDS/<slug>`` fallback now ends
  in "…" when truncated.
- **P1 byte-equality smoke**: ``test_apollo_17_committed_png_matches_fresh_render``
  re-renders apollo-17 and compares bytes to the on-disk PNG;
  silent renderer drift now trips CI.
- **P2 frontmatter regex**: trailing-newline tolerance via
  ``(\n|\Z)`` end-anchor.
- **P2 file size**: split ``finds_og.py`` (191 LoC, near warn) into
  orchestrator + ``finds_og_layers.py``; both now well under 200.
- **LOW escaped quotes**: ``_strip_yaml_string`` unescapes ``\"`` /
  ``\'`` in YAML scalars (was rendering as literal backslash).
- **LOW slug sanitize**: ``_assert_safe_slug`` rejects ``..`` / ``\``
  / absolute paths before writing the PNG.
- **vaivora #12 deploy chain**: wired both OG scripts into
  ``deploy-cf.yml`` (PR #18) before ``npm run build`` with
  setup-python pinned to the same SHA used in poll-pursue.yml. Added
  the OG sources to the ``paths:`` trigger.
- **vaivora #13 dedup**: extracted ``og_writer.write_deterministic_png``;
  both ``og_image.py`` and ``finds_og.py`` now share one writer for
  the byte-stability postlude.
- **Codex P2 inline cards**: parser handles ``cards: ["a", "b"]``
  flow-list shape (was silently dropping to ``()``).
- **Test patch**: updated ``test_deploy_ui_workflow_regenerates_og_image``
  → ``test_deploy_cf_workflow_regenerates_og_image`` (deploy-ui.yml
  retired in PR #18).

Validation: 205/205 pytest pass, npm run build clean,
``bpsai-pair arch check`` clean on all touched files,
``yaml.safe_load`` parses ``deploy-cf.yml`` cleanly.

### Session: 2026-05-09 — Per-entry OG images for /finds/<slug> (PR #20)

Follow-up to PR #7 (real OG image + per-route hook). Each /finds entry
now ships its own 1200×630 OG card so individual shares get a unique
preview instead of inheriting the default `og.png`. Composition reuses
the declassified-document chrome (corner brackets, terminal header,
DECLASSIFIED stamp, manifest sha line, footer status pill) and replaces
the PURSUE://INDEX lockup with the entry title (wrapped to 3 lines max,
ellipsized), subtitle (truncated to one line), and an "AGENCY · prefix"
source label resolved against the manifest.

11 entries × ~85 KB each = ~984 KB committed under `web/public/og/finds/`.

Files added:
- `src/pursue_index/web/finds_og.py` — orchestrator + drawing layers (191 LoC)
- `src/pursue_index/web/finds_frontmatter.py` — minimal MDX YAML-FM parser, no PyYAML dep (105 LoC)
- `scripts/build_finds_og_images.py` — CLI, idempotent, byte-stable (102 LoC)
- `tests/unit/test_finds_og_image.py` — 13 tests (composition, byte-stability, frontmatter, layout wiring, all-entries smoke test)
- `web/src/pages/finds/[slug].astro` — passes `ogImage={`${base}/og/finds/${entry.id}.png`}` to Base

Validation:
- 13 new tests pass; full suite 177 passed (no regressions)
- `bpsai-pair arch check` clean on all four new files
- `npm run build` clean (169 pages built); rendered HTML verifies `og:image` resolves to `https://pursueindex.com/og/finds/<slug>.png`
- Byte-stability confirmed across two consecutive script runs (apollo-17.png sha = `04b57b4487a04614…`)

Trade-offs flagged in PR body:
- New finds entries require running `python scripts/build_finds_og_images.py` before deploy. The `test_all_finds_entries_have_committed_og_images` smoke test catches missing PNGs in CI.
- Per task instruction, the GH Actions deploy workflow was NOT modified; operator will wire `build_finds_og_images.py` into deploy-cf.yml (or deploy-ui.yml) post-merge.

PR: https://github.com/BPSAI/pursue-index/pull/20 — branch `feat/per-entry-og-images`, do NOT merge.

### Session: 2026-05-09 — Eight-PR shipping batch (autonomous)

After the public launch closed cleanly, ran a parallel-feature batch
through full-review-and-fix workflow. **Eight PRs shipped to main**;
each went through nayru (code) + laverna (security) + vaivora
(cross-cutting) + chatgpt-codex-connector reviews; every legitimate
finding fixed regardless of P value before merge. Squash-merge
commits below.

| PR | Title | Squash | Highlights |
|----|-------|--------|------------|
| #2 | alex-zhang42 VLM image-description ingest | `6eef33c` | atlas_join + augmented embed; 1,208 pages augmented; provenance + sha256 sidecar |
| #3 | Auto-poll for new PURSUE tranches | `8372fd3` | Layer 1: cron `0 */6 * * *` GH Actions, curl_cffi fetch + sha compare, auto-issue on change/failure; SHA-pinned actions + Dependabot |
| #4 | /api documentation page | `2ea897c` | Public docs for /api/retrieve + /api/chat; constants imported from worker/chat_kv.js so doc drift trips CI; SECURITY.md added |
| #5 | Faceted filters on /search | `1176bef` | Agency + date range + redacted-only; URL-state sync preserves utm/fbclid; ChatIsland post-filters citations to match |
| #6 | 2D semantic browser at /atlas | `27b3de3` | UMAP `random_state=42`, regl-scatterplot 1.16.0 pinned, MiniSearch parity with /search, atomic write, mobile cluster-list fallback |
| #7 | Real OG image + share metadata | `06a15b2` | Pillow >= 11.1.0 (CVE-2024-28219 patched), byte-stable PNG, resolveOgImageUrl validator, deploy-ui.yml regen step |
| #8 | Reader-mode ↔ iframed PDF page sync | `c89cb5e` | iframe.src honestly debounced (250ms), sandbox="allow-scripts allow-same-origin", protocol guard rejects javascript:/data:/http:/file: |
| #16 | Worker /api/* fall-through | `e7b5c99` | Hot-fix: WORKER_API_PATHS allowlist so /api docs serves; reciprocal cross-references between worker/index.js and api.astro |

Context plans landed alongside (operator decision pending):

- `.paircoder/plans/black-vault-reference.md` — REFINE-FIRST → LAUNCH after Greenewald permission. Threshold recalibration is the load-bearing follow-up.
- `.paircoder/plans/llm-cleaned-reading-text.md` — REFINE-FIRST. Pilot 30 cards before full-corpus ($8 cached, Option C storage).

Deleted post-merge per the doc-cleanup pattern:

- `.paircoder/plans/alex-zhang-ingest.md` (shipped in PR #2)
- `.paircoder/plans/auto-poll-tranches.md` (shipped in PR #3)
- `.paircoder/plans/finds-candidates.md` (5 mdx entries shipped during launch)
- `.paircoder/plans/semantic-browser.md` (shipped in PR #6 — fix-driver deleted in their commit)

For per-PR review verdicts and the full finding list, see the
GitHub PR comments on each squashed PR. Reviewer artifacts are
preserved in `.claude/agent-memory/{nayru,laverna,vaivora}/`.

### Session: 2026-05-09 — Re-OCR full corpus auto-mode (background)

Operator authorized `pursue ocr run --engine auto --force` against
the full 4,153-page corpus while AFK. Background bash PID 2738434
(>56 minutes runtime as of CF-deploy-check). Surya GPU primary +
LLM fallback on sub-threshold pages. After completion the operator
will re-run `pursue embed run --augment-from
data/external/alex-zhang42-corpus.jsonl` and republish the search
payload. Cost ~\$1.36 at Haiku rates per the OCR benchmark.

### Session: 2026-05-09 — Post-launch cleanup

- **Polish patch (commit `82f6a2c`):** Removed dead splash/preview-gate
  machinery (web/src/pages/splash.astro, magic-link routes, cookie
  helpers, RFC-6265 cookie test). Fixed `RATE_LIMIT = 100` → `5`
  FIXME that should have been flipped at gate-flip but wasn't —
  20x quota exposure closed (daily $100 spend cap was already in
  place so worst-case bill was bounded). Added Related Work section
  to /methodology crediting alex-zhang42's parallel release. Tests:
  56 worker / 79 python green; 162-page build clean.
- **Doc cleanup:** Deleted 9 completed plans + post-launch artifacts
  (chat-interface, embed-stage, novelty-detection, ocr-benchmark,
  ocr-gpu-surya, ocr-llm-fallback, phase-2-roadmap, production-launch,
  ui-redesign-alien plans; launch-readiness/STATE.md;
  cloudflare-pages-migration runbook). README rewritten to reflect
  public-launch reality. project.md refreshed (pipeline diagram now
  shows actual `embed → serve` flow, tech stack lists shipped
  surface, license updated to Apache-2.0).

### Session: 2026-05-09 — Launch-readiness QC pass + gate flip

- Two real-user fixes pushed to prod (`815844b`):
    - /methodology License section now references Apache-2.0 with
      links to apache.org and /cite (was: "License: TBD before public
      launch")
    - CITE entry added to main nav between METHODOLOGY and SUPPORT
- Repo flipped public + GitHub interaction limits applied
  (`existing_users`, expires 2026-11-09).
- Divona QC sweep on prod: 19 scenarios across 5 critical/regression
  suites — smoke 4/4, chat 3/3 (4 read-only-skipped as designed),
  cite 4/4, mobile 3/3, support 5/5. Zero failures. GO issued.

### Session: 2026-05-09 — Novelty detection (machinery + UI)

- `pursue novelty compute` CLI + machinery: cosine top-1 vs reference
  index → card-level disclosure_status (novel / partial /
  previously-disclosed). Synthetic placeholder reference corpus
  (10 hand-crafted public-domain UFO-adjacent passages: Roswell 1947,
  Project Blue Book, Hottel memo, RB-47, Malmstrom, etc.).
- UI: index page DISCLOSURE filter chip; card detail page Provenance
  panel showing top-3 reference matches.
- Black Vault integration deferred to post-launch backlog.

For deeper history see `git log` — older sessions covered the CSV
pivot (Akamai bypass via curl_cffi), Surya GPU OCR engine landing,
LLM fallback + auto-mode, full corpus passes, OCR benchmark report,
embed stage, chat interface end-to-end, custom domains, security
hardening, git history scrub.

## What's Next

### Immediate (launch comms — operator-driven)

1. Watch HN for dang's response on the flagged Show HN. The retitled
   post was submitted with the email already sent.
2. Reddit r/UFOs + r/DataHoarder — monitor comments, respond to
   genuine technical questions. Add cross-link to alex-zhang42's
   project on the r/DataHoarder thread (highest-leverage cross-credit
   move).
3. The War Zone email — wait for response (1-3 day cycle).

### Post-launch backlog (priority order)

1. **Curated Finds expansion** — current 11 entries is intentionally
   small to set the editorial bar. Plan:
   `.paircoder/plans/curated-finds.md`.
2. **LLM-cleaned reading text overlay** — pilot 30 cards, calibrate
   prompt against diff review, then full corpus (~\$8 cached, Option C
   storage). Plan: `.paircoder/plans/llm-cleaned-reading-text.md`.
3. **Black Vault reference corpus** — REFINE-FIRST → LAUNCH after
   Greenewald permission. Threshold recalibration in
   `aggregate.py` is the load-bearing follow-up. Plan:
   `.paircoder/plans/black-vault-reference.md`.
4. **Review-and-correct pipeline** — accept community OCR
   corrections via GitHub issues; flow them back into the index.
   Plan: `.paircoder/plans/review-correct.md`.
5. **Per-entry OG images for `/finds/[slug]`** — `ogImage` prop hook
   already wired in `Base.astro`; byte-stable `OgImageContext` can
   be looped per-slug. Defers from PR #7.
6. **Integration-boundary smoke test for `/api/*` dispatch** —
   vaivora finding on PR #16. Worker tests stub ASSETS; web tests
   don't run the Worker. A `wrangler dev` + curl harness would have
   caught the original PR #4 regression. Either a CI job or a
   post-deploy probe.

### Optional cleanup

- Delete the local `pre-scrub-backup-*` git tag once you're confident
  the history scrub stuck.

## Blockers

**Possible CF deploy lag** (2026-05-09 14:10 local) — after the
8-PR merge batch completed, `https://pursueindex.com/atlas/` and
`https://pursueindex.com/api/` are still returning 404 from the
edge while the homepage + `/finds/`, `/search/`, etc. all serve
the new builds correctly. Either CF Workers Builds is still
processing the most recent merges OR the build is failing on a
new dep (regl-scatterplot? Pillow 12?). Worth checking the CF
dashboard build log if 404s persist past ~15 min from the last
merge. The Worker fix in PR #16 (`e7b5c99`) explicitly enables
`/api/` to fall through to ASSETS, so once CF deploys both the
docs page and `/atlas` should resolve.

## Quick Commands

```bash
# Pipeline (re-runnable, idempotent against the manifest)
pursue scrape run
pursue download run --manifest data/manifests/latest.json
pursue ocr run --manifest data/manifests/latest.json --engine auto
pursue embed run --manifest data/manifests/latest.json

# Lightweight upstream-CSV poll (Layer 1 of auto-poll-tranches.md)
# Runs on GH Actions cron every 6h; this is the manual operator path.
python scripts/poll_pursue.py

# Tests
pytest -x                     # python, 79 tests
npm --prefix worker test      # worker, 56 tests
cd web && npm run build       # web, 162 pages

# Web dev
cd web && npm run dev         # localhost:4321

# Worker dev (against real KV + secrets)
npx wrangler dev

# QC
bpsai-pair qc list
/run-qc --env prod

# Status
bpsai-pair status
```
