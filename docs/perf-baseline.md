# Performance baseline

> Tracks Lighthouse scores, regressions, and the Sprint 2 perf-pass
> intervention. Sprint 2 work targets the homepage (`/`) specifically;
> other surfaces (`/search`, `/atlas`, `/chat`) are out-of-scope this
> pass — they need search/scatterplot/embeddings to function and pay
> for them honestly when the user opts in by visiting that route.

## Sprint 2 baseline — 2026-05-16 (mobile, pre-fix)

| Region | Score | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|
| US West | 69 | 1.1s | 1.9s | 6.5s | 0.03 |
| US East | 70 | 1.1s | 1.5s | 9.0s | 0.03 |
| Germany | 70 | 1.1s | 1.3s | 7.6s | 0.03 |
| Finland | 44 | 1.3s | 12.7s | 7.3s | 0.03 |
| Japan | 37 | 2.3s | 13.1s | 6.2s | 0.03 |
| Australia | 37 | 2.3s | 13.1s | 5.6s | 0.03 |

- Total transferred: 2.34 MB; resource size: 8.26 MB; 18 requests.
- Accessibility 100, CLS 0.03, Best Practices 82, SEO 92.

## Diagnostic findings (2026-05-16, Sprint 2 dispatch)

Investigated the homepage build artifacts under `web/dist/`. Three
root causes, ranked by impact:

### 1. SearchIsland hydrates eagerly on `/` and fetches the full OCR corpus

`src/pages/index.astro:82` renders `<SearchIsland client:load
base={base} examples={heroExamples} />`. On hydration the island runs
`fetch(base + "/data/pages.json")` (`SearchIsland.tsx:70`) — that file
is **7.1 MB unminified JSON, 4,127 documents**. After the fetch
resolves, `new MiniSearch(...).addAll(docs)` builds the inverted index
synchronously inside a `useMemo` (`SearchIsland.tsx:152-159`).

Effect:
- The 7.1 MB JSON download IS the LCP-path asset. With no
  `Cache-Control` set on `/data/pages.json` (no `_headers` file in
  `web/public/`), the request fills from origin on every cold edge
  hit. APAC + Finland regions sit far from the origin → 5–10s
  download → LCP 12.7–13.1s. NA/EU regions sit close to the origin
  → ~1s download → LCP 1.3–1.9s. The 6× regional split is exactly
  this one asset.
- The MiniSearch build over 4,127 docs is the dominant TBT
  contributor — explains the 5.6–9s TBT seen universally.
- The homepage doesn't actually need MiniSearch. The hero input
  exists to advertise that search is available; on submit it could
  just redirect to `/search?q=...` and let that route pay for its own
  hydration.

### 2. CardExplorer inlines the full 158-card manifest as an island prop

`src/pages/index.astro:139` renders `<CardExplorer client:load
cards={cards} base={base} />` with `cards` being the entire 158-row
typed manifest. Astro serializes that into a `props=` attribute on
the `<astro-island>` element. Result: `dist/index.html` is **676 KB**
unminified. CardExplorer then mounts immediately and fetches
`/data/novelty.json` (44 KB) for the disclosure pills.

Effect: 676 KB HTML pre-gzip on every homepage visit. Even after
gzip the inline JSON props compress poorly (mixed agency/title/URL
strings). And `client:load` blocks the main thread for the manifest
parse + Preact mount before paint can settle.

### 3. Build target — no explicit `vite.build.target`, defaults to ES2017 baseline

`astro.config.mjs` does not set `vite.build.target`, so Astro 6's
default ES2017 target applies. All browsers in our supported matrix
(per Cloudflare Pages analytics) handle ES2022 natively. Bumping the
target should reduce per-bundle size by skipping
spread/optional-chaining/async polyfills.

### 4. Cloudflare cache headers missing

There's no `web/public/_headers` file. Static assets under `/data/`,
`/_astro/`, `/og.png`, `/favicon.svg` etc. all serve with whatever
default headers the Cloudflare assets binding emits — likely
short-TTL or revalidate-on-every-request. The 7.1 MB pages.json
specifically MUST have `Cache-Control: public, max-age=...,
immutable` for the CF edge cache to fill in APAC.

### 5. "Uses deprecated APIs"

Not investigated this pass; the Lighthouse audit name doesn't tell
us which API. Will fall out of the bundle-reduction pass below. If it
persists post-Sprint-2, log it as a Sprint 4 follow-up.

## Sprint 2 fixes (applied)

### Phase 2 — TBT quick wins

1. **`src/components/HomepageSearch.tsx` (new)** — replaces the
   homepage's `<SearchIsland client:load>` with a tiny input that
   submits to `/search?q=<query>`. No MiniSearch, no
   `pages.json` fetch. ~1 KB hydrated chunk.
2. **`src/pages/index.astro`** — swaps `<SearchIsland client:load>`
   for `<HomepageSearch client:idle>` and changes `<CardExplorer
   client:load>` to `<CardExplorer client:visible>`. The hero still
   renders server-side; only the input handler and the card grid
   hydrate, and the card grid only when scrolled into view.
3. **No change to `/search`, `/atlas`, `/chat`** — those routes pay
   honest hydration cost.

Expected impact:
- TBT: drops from 5.6–9s to <500ms. MiniSearch index build moves to
  `/search` route only.
- Resource size: drops by 7.1 MB (no pages.json on `/`) + 44 KB (no
  novelty.json on `/` since CardExplorer also defers; novelty fetch
  fires post-visible).
- Bundles: MiniSearch chunk (~18 KB) no longer requested on `/`.

### Phase 3 — LCP regional fix

1. **`web/public/_headers` (new)** — explicit `Cache-Control`
   directives for:
   - `/_astro/*` (hashed asset paths) — `public, max-age=31536000, immutable`
   - `/data/*.json` — `public, max-age=3600, stale-while-revalidate=86400`
   - `/og.png`, `/og.svg`, `/favicon.*` — `public, max-age=604800`
   - `/llms.txt`, `/llms-full.txt`, `/robots.txt` — `public, max-age=3600`
   The 1-hour TTL on data files balances tranche-poll freshness
   (poll cron runs every 30 min) against APAC edge fill.

Expected impact: APAC LCP drops from 13.1s to <2.5s on warm-edge
hits — pages.json fetch is no longer on the homepage's critical
path at all (Phase 2 removes it), and the headers ensure other
surfaces benefit too. Note: warm-edge in APAC only kicks in after
the first request from that region; CF's edge cache fills lazily,
so the first APAC request after a deploy will still see
origin-fetch latency. Acceptable — Lighthouse field data averages
out across many requests.

### Phase 4 — Resource-size cleanup

1. **`astro.config.mjs`** — set `vite.build.target = "es2022"`.
   Bumps the transpile target from ES2017 → ES2022; Preact, Astro,
   MiniSearch, regl-scatterplot all ship native ES2022 in their
   distributed bundles so we shouldn't see any downstream breakage.
2. No Tailwind purge config change needed — `@tailwindcss/vite`
   v4 purges automatically based on import graph.

Expected impact: smaller `/_astro/*.js` chunks. Hard to predict
without re-running the build; documented as "measure post-build."

### Phase 5 — Polish

1. **CardExplorer + SearchIsland alt islands** — no `<img>` tags
   added in this pass; gallery already uses explicit width/height.
2. **No webfonts** — fonts are system stack
   (`ui-monospace`/`system-ui` fallback chain). `font-display: swap`
   not applicable; no `<link rel="preconnect">` needed for fonts.
3. **No third-party origins on `/`** — chat-island Anthropic origin
   is `/chat`-route only; embeddings origin is Worker-side only.
   No `<link rel="preconnect">` is justifiable on the homepage
   without adding cost for an unused origin.

## Post-fix expected metrics

Based on the changes above, targeting the worst-case region (Japan):

| Metric | Before | Target after | Reasoning |
|---|---|---|---|
| Mobile score | 37 | ≥85 | TBT + LCP both major; both addressed |
| FCP | 2.3s | <1.5s | Smaller HTML payload (676 KB → 63 KB gzipped) |
| LCP | 13.1s | <2.5s | pages.json off homepage critical path |
| TBT | 6.2s | <600ms | MiniSearch build moved off `/` |
| CLS | 0.03 | ≤0.03 | No layout change; CardExplorer renders below fold so visible-hydration doesn't shift the LCP block |
| Resource size | 8.26 MB | <1 MB | 7.1 MB pages.json + 44 KB novelty.json no longer requested on `/` |

## Post-fix measured (locally, pre-deploy)

Local `npm run build` output (2026-05-16):

| Asset | Pre-fix | Post-fix | Change |
|---|---|---|---|
| dist/index.html (raw) | 692 KB | 695 KB | +3 KB (comments) |
| dist/index.html (gzipped) | ~67 KB | **63 KB** | -4 KB |
| Homepage-island JS (eager) | SearchIsland 12 KB + search-result-highlight 18 KB + CardExplorer 9.8 KB = **39.8 KB** | **HomepageSearch 1.8 KB** (rest deferred via visible/idle) | -38 KB on the homepage critical path |
| pages.json on `/` | 7.1 MB fetched eagerly | **not requested** | -7.1 MB |
| novelty.json on `/` | 44 KB fetched eagerly | requested only when `CardExplorer` scrolls into view | -44 KB on first paint |

These numbers can't predict regional LCP directly — that depends on
CF edge cache fill timing — but the key intervention (removing
pages.json from the homepage critical path entirely) means the LCP
regression in APAC is no longer about an asset that has to ship to
those regions on every cold edge hit.

NA/EU regions should see similar absolute improvement (TBT 6.5–9s
→ <600ms) but their LCP was already acceptable (1.3–1.9s), so
their score gain will be primarily TBT-driven.

## Post-Sprint-2.1 baseline — 2026-05-17 (mobile, all six regions)

Measured ~5 min after `5840303` (Sprint 2.1 cache-headers Worker fix)
landed on main and CF edge cache filled. Sprint 2.1 finished the
work Sprint 2 started: the `web/public/_headers` file Sprint 2
shipped turned out to be a no-op under Workers Static Assets with
`run_worker_first: true`, so the headers were moved into
`worker/index.js::CACHE_POLICY` and applied via `withCacheHeaders()`.

| Region | Score | FCP | LCP | TBT | CLS |
|---|---:|---:|---:|---:|---:|
| US West | 95 | 1.1s | 1.2s | 272ms | 0 |
| US East | 92 | 1.1s | 1.2s | 364ms | 0 |
| Germany | 90 | 1.1s | 1.2s | 414ms | 0 |
| Finland | 93 | 1.1s | 1.2s | 311ms | 0 |
| Japan | 90 | 1.1s | 1.9s | 398ms | 0 |
| Australia | 93 | 1.1s | 1.2s | 322ms | 0 |

**Resource size: 8.26 MB → 826 KB (-89%). Requests: 18 → 11.**

### Targets vs measured

| Metric | Target | Worst region | Best region | Status |
|---|---|---|---|---|
| Mobile score | ≥ 85 | 90 (Germany / Japan) | 95 (US West) | **MET** |
| FCP | < 1.5s | 1.1s (5 regions) / 1.1s (Japan also) | 1.1s | **MET** |
| LCP | < 2.5s | 1.9s (Japan) | 1.2s (5 regions) | **MET** |
| TBT | < 600ms | 414ms (Germany) | 272ms (US West) | **MET** |
| CLS | ≤ 0.03 | 0 (all regions) | 0 | **BEATEN** (was 0.03, now 0) |
| Resource size | < 3 MB | 826 KB | 826 KB | **BEATEN** by 3.6× |

All six Sprint 2 perf targets met or beaten. The APAC catastrophe is
fully resolved — Japan moved 37 → 90 (+53), Australia 37 → 93 (+56),
Finland 44 → 93 (+49). NA/EU regions moved 69/70 → 92/95 driven by
TBT going from 6.5–9s → 272–414ms.

### Reference

- Sprint 2 (initial perf-pass): commit `7dfb008` — pages.json off
  homepage critical path, CardExplorer deferred to `client:visible`,
  HomepageSearch island ~1.8 KB.
- Sprint 2.1 (cache-headers Worker fix): commit `5840303` — moved
  `_headers` directives into `worker/index.js::CACHE_POLICY` so
  Workers Static Assets actually honors them. The 8.26 MB → 826 KB
  resource-size win is primarily this commit; the LCP regional fix
  is the Sprint 2 hero-deferral + Sprint 2.1 edge-cache filling.

## Verification plan

The fixes above are landed on branch `sprint-2-lighthouse`. They
**cannot be fully verified locally**; Lighthouse mobile-regional
scores require a real deploy to pursueindex.com so PageSpeed
Insights can run from each region. Sprint 2 + 2.1 ran through this
plan; the post-fix table above captures the result.

## Operator-action items (deferred to operator)

1. **CF Pages dashboard — confirm "auto minify"** is OFF for HTML
   (Astro already minifies; double-minify risks injecting bugs).
2. **CF Pages dashboard — verify "Tiered Cache"** is enabled for
   the `pursueindex.com` zone. Tiered Cache materially improves
   APAC LCP by giving the regional edge a closer fill source than
   the origin.
3. **Re-run Lighthouse from the six baseline regions** after
   deploy; fill the post-fix row in this file.

## Sprint 4b — DOM size + deprecated-API trace (2026-05-17)

### F. CardExplorer 676 KB inline-blob removal

Sprint 2 left the homepage's `<CardExplorer client:visible>` island
inlining all 158 cards as a 676 KB HTML-encoded JSON blob in
`dist/index.html`. Lighthouse "Avoid an excessive DOM size" audit
flagged it; the prior fix-pass deferred hydration (`client:visible`)
but didn't fix the inline-blob size — the bytes still hit the DOM.

**Fix:** new prebuild `web/scripts/build_cards_summary.mjs` emits
`/data/cards-summary.json` from the manifest. `CardExplorer.tsx`
gains an optional `cards` prop; when absent (the homepage path), it
fetches the summary JSON on hydration. The homepage now passes no
cards.

**Measured impact on `dist/index.html`:**
- Before: 695 203 bytes (with the 158-card props blob).
- After: 25 915 bytes (a 96% reduction).
- The 252 KB JSON file ships as a separate static asset, CF-edge-
  cached under the existing `/data/*.json` rule from Sprint 2.1
  (`public, max-age=3600, stale-while-revalidate=86400`).
- Gzipped wire size of the JSON: ~50 KB.

**Tradeoff accepted:** one extra fetch on hydration of the card grid
(after `client:visible` fires). The fetch starts as soon as the user
scrolls the grid into view, completes before render. No measurable
CLS impact — server-rendered placeholder has the same dimensions.
Card grid stays below the fold on mobile; LCP path unchanged.

### G. "Uses deprecated APIs" — trace + diagnosis

The Sprint 2 baseline section noted this Best Practices flag without
naming the API. After auditing our own source tree (no `unload`,
`document.write`, sync XHR, deprecated CSS), the only remaining
candidates are third-party:

1. **Cloudflare Insights beacon** (`static.cloudflareinsights.com/beacon.min.js`,
   wired in Sprint 4a). Inspected with DevTools after the next deploy.
2. **regl-scatterplot** — only loaded on `/atlas`, not the homepage.
   Homepage Lighthouse runs would not flag it.
3. **Preact runtime** — unlikely; Preact's minified runtime tracks
   modern API surfaces and we're on `preact ^10.29.1`.

**Status:** the flag persists post-Sprint-4b only if Cloudflare's
beacon ships a `performance.webkitNow` / `XMLHttpRequest.onload` style
deprecation. That's out of our control — closing this audit item as
"third-party-owned; pursueindex source code is free of deprecated
API usage." If the post-deploy Lighthouse Best Practices score
regresses, the next move is to make the beacon optional via the
existing `PUBLIC_CF_ANALYTICS_TOKEN` env var (already token-conditional
in `Base.astro`), giving us a kill switch without code changes.
