---
id: production-launch
type: feature
status: backlog
created: 2026-05-08
depends_on: [chat-interface, ocr-benchmark, review-correct]
priority: high
---

# Production launch — pursueindex.{com,ai}

## Why

This is the gate between "internal scaffold" and "thing journalists can
quote." Everything before this can be iterated quietly; everything after
is public and indexed and screenshotted.

## Pre-launch checklist

### Repo

- [ ] Flip `pursue-index` to public, OR fork the publishable subset
      (web/, docs/, manifests, scripts/) into `pursueindex-public` and
      keep the workstation-side ops repo private. Latter is cleaner —
      the ops repo holds .env templates, NAS paths, agent memories, etc.
- [ ] Update `astro.config.mjs` site/base for the public domain.
- [ ] Add a public `LICENSE`. The user-facing site code is BPS-owned;
      the manifest data is public domain.

### Infra

- [ ] DNS: pursueindex.com → CNAME to GitHub Pages (or Cloudflare Pages
      if we move). pursueindex.ai → A record to Workers / Vercel for the
      chat API.
- [ ] Cloudflare in front of the static site for DDoS + global cache +
      analytics-without-cookies.
- [ ] Workers KV namespace for rate limits + semantic cache.
- [ ] Anthropic API key in Workers secrets; budget alert at $50/day.
- [ ] Observability: a single Cloudflare Logpush → simple dashboard for
      latency, cache hit rate, abuse-flag count.

### Content

- [ ] `/about` — what this is, who built it, why.
- [ ] `/methodology` — how the corpus is fetched, OCR'd, validated.
      Publish the benchmark numbers from `/benchmark`. Be honest about
      limitations (handwriting, redactions, OCR error rates).
- [ ] `/faq` — "How accurate is the OCR? Can the chat be wrong? Why
      these documents? Will you add more? Can I download the data?"
- [ ] `/api` — public read API doc for the manifest + page text. Yes,
      let people scrape us properly. It's public domain.
- [ ] Sample queries on the chat empty state, picked to demonstrate
      both range and abstention.

### Hardening

- [ ] Per-IP rate limit: 30 chats/hr.
- [ ] Global daily budget cap with graceful fallback to keyword search.
- [ ] Prompt-injection detection at the edge (regex pre-filter + log).
- [ ] Semantic cache for the top-100 expected queries pre-warmed.
- [ ] Synthetic load test: 100 RPS for 60s, p95 latency < 5s.
- [ ] Abuse playbook: who gets paged, what gets disabled, how to roll
      back to read-only.

### Launch comms

- [ ] HN post drafted (Show HN: pursueindex.com — searchable index of
      DOW PURSUE UAP releases). Title under 80 chars, lede in first
      paragraph, methodology link in second.
- [ ] X/Bluesky teaser post drafts.
- [ ] Journalist outreach short-list:
  - The War Zone (Tyler Rogoway, Joseph Trevithick) — Drive-staffed
    aviation/national-security beat.
  - Defense News.
  - VICE Motherboard.
  - 404 Media.
  - The Black Vault (John Greenewald) — UAP FOIA community OG, would
    appreciate the methodology focus.
  - r/UFOs, r/HighStrangeness — careful, they will both love and
    over-interpret the chat.
- [ ] "How to cite this" snippet (for academic / journalist usage).

## Post-launch

- [ ] First-week monitoring: any chat answer that goes viral gets
      manually reviewed. If wrong, page is corrected, change is logged
      in `data/corrections/`.
- [ ] Public changelog page so journalists can see "released X on
      date Y; corrected page Z on date W."
- [ ] Inbound feedback intake — `feedback@pursueindex.com` or a form.

## Acceptance

- pursueindex.com resolves and serves the redesigned UI under HTTPS.
- Chat works against the public Workers endpoint with auth-free CORS
  from pursueindex.com only.
- Rate limit holds under synthetic load.
- HN post is in draft and ready to ship; methodology page is live.
- No staging-only assets, no debug logs, no API keys leaked in client
  bundle (verify with a quick scan of `web/dist/`).

## Out of scope for v1.0

- Newsletter / mailing list.
- Premium / paid tier.
- Comments or community features.
- User accounts.
- Multi-language UI (English first).

These are all good ideas for v1.1+ but every one of them grows the
attack surface and the support burden. Ship narrow, ship correct.
