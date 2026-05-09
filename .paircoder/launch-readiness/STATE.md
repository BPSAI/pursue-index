# Launch state — 2026-05-09

## Site is live and gate is being flipped

- Domain: pursueindex.com (Cloudflare Workers + Static Assets)
- 163 pages built, 65 worker tests + 79 pytest green
- Apache-2.0 LICENSE + NOTICE
- Footer credits BPS AI Software + PairCoder
- Git history scrubbed of OAuth-token references and launch comms drafts
- HTTP smoke pass: all 16 routes 200; security headers complete; CSP active; CORS lockdown verified; /api/retrieve + /api/chat both work; chat tested live, citations + abstention discipline confirmed.

## Gate-flip changes (this commit)

1. `worker/chat_kv.js`: `RATE_LIMIT` 100 → 5
2. `worker/index.js`: drop cookie-gate from `/` and `/api/*`, keep splash route as a fallback
3. `web/src/layouts/Base.astro`: `noindex` default true → false
4. `web/public/robots.txt`: replace `Disallow: /` with permissive crawl + sitemap pointer

## Post-flip (still pending)

- `gh api -X PUT /repos/BPSAI/pursue-index/interaction-limits -f limit=existing_users -f expiry=six_months` (becomes available once repo flips public)
- Post HN draft (operator has local copy of `docs/launch/hn-post.md`)
- Sequenced journalist outreach (operator has `docs/launch/journalist-outreach.md`)
- Run divona QC interactively via `/chrome` + `/run-qc` for the things HTTP smoke can't cover (streaming UX, mobile, click-through, settings panel)

## Optional cleanup

- Drop the splash route entirely once gate is verified flipped (delete `web/src/pages/splash.astro` + the splash branch in `worker/index.js`)
- Delete `pre-scrub-backup-*` tag locally once you're sure scrub stuck
