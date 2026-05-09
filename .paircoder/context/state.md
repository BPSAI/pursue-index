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

### Session: 2026-05-09 — PR #19 review-fix follow-up (`feat/api-integration-smoke`)

Pushed `e39787e` to PR #19 addressing every legitimate review finding
across laverna (1 MED + 2 LOW), nayru (5 P1 + 3 P2), vaivora (4
latents), and chatgpt-codex-connector (2 line-level). One bundled
follow-up commit; no changes to merge state.

Hardening applied (behavior of the 6 dispatch assertions unchanged):

- Wrangler pinned as `web/` devDependency (`^4.90.0` + lockfile);
  smoke now invokes `web/node_modules/.bin/wrangler` instead of
  `npx --yes wrangler`. Workflow runs `npm ci` before the smoke step
  so the pin is present.
- Workflow uploads wrangler dev log artifact on failure; smoke
  honors `SMOKE_KEEP_LOG=1` so the cleanup trap doesn't `rm` it.
- Readiness curl gets `--max-time 5`; assertion 2 gets `--max-redirs 3`.
- `${arr[@]+"${arr[@]}"}` idiom for bash-3.2 / macOS compat under -u.
- Workflow path filter adds `web/astro.config.mjs` and
  `web/package*.json` (build inputs that produce smoke's input file).
- `mktemp` invocations have explicit failure handling.
- Assertion 5 also asserts `Content-Type: text/html*` so the
  "ASSETS HTML, not Worker JSON" contract is checked at the type
  level, not just by substring exclusion.
- Script consolidates to `set -euo pipefail`; header documents the
  `.dev.vars` secrets caveat and the `wrangler dev` ↔ prod parity gap
  (CORS / OPTIONS / `not_found_handling: "404-page"` not exercised).
- Cross-pointers between `scripts/smoke_api_dispatch.sh`,
  `web/scripts/test-api-page.mjs`, and `worker/index.js`'s
  `WORKER_API_PATHS` declaration so future editors see all three.
- On non-zero exit, full wrangler log preserved at
  `/tmp/wrangler-smoke-last.log` (local) and
  `$GITHUB_WORKSPACE/wrangler-smoke.log` (CI artifact).

Validation: smoke script ran locally against wrangler 4.90.0 + freshly
built `web/dist`; all 7 assertions passed. New static-shape test at
`tests/unit/test_smoke_api_dispatch_hardening.py` (19 tests, all
passing) pins each fix to prevent silent regression. Full suite
green: 183 passed, 0 failed. Arch check clean on every modified file.
Push only — branch not merged; CI re-runs on push event.

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
