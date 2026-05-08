# Runbook — migrate to Cloudflare Pages + custom domains

> Target: pursueindex.com → canonical site, pursueindex.ai → 301 redirect
> Domains: registered at Namecheap; DNS will move to Cloudflare
> Repo: BPSAI/pursue-index (private)

This is a one-time setup. After it's done, every push to `main` that
touches `web/**` redeploys via Cloudflare Pages, and the GitHub Pages
workflow becomes a backup we can disable later.

## 1. Cloudflare account + DNS migration

If you don't have a CF account yet, create one (free tier is fine).

For each domain, in CF dashboard:

1. **Add site** → enter `pursueindex.com` → Free plan.
2. CF auto-imports any DNS records currently at Namecheap. Review what's
   there; for a fresh domain there should be little or nothing.
3. CF gives you two CF nameservers (e.g.
   `aria.ns.cloudflare.com`, `gabe.ns.cloudflare.com`).
4. Open Namecheap → Domain List → `pursueindex.com` → Manage → Nameservers
   → switch from "Namecheap BasicDNS" to "Custom DNS" → paste the two CF
   nameservers → save.
5. Repeat for `pursueindex.ai`.

Propagation is usually < 15 min, can take up to 24h. CF will email when
verified.

## 2. Connect repo to Cloudflare Pages

Once at least `pursueindex.com` shows verified in CF:

1. CF dashboard → **Workers & Pages** → **Create application** → **Pages**
   tab → **Connect to Git**.
2. Authorize the **Cloudflare Pages** GitHub App. When prompted, install
   it on the **BPSAI** organization with access to `pursue-index` (or all
   repos — your call).
3. Pick `BPSAI/pursue-index` from the list. Production branch: `main`.
4. Build config:
   - **Framework preset:** Astro
   - **Build command:** `cd web && npm install && npm run build`
   - **Build output directory:** `web/dist`
   - **Root directory:** *(leave blank)*
   - **Environment variables:** `NODE_VERSION=22`
5. Save and deploy. First build runs immediately; takes ~1 min.
6. After success, you get a `<project>.pages.dev` preview URL (e.g.
   `pursue-index.pages.dev`).

## 3. Wire pursueindex.com to the Pages project

In the CF Pages project → **Custom domains** → **Set up a domain**:

1. Enter `pursueindex.com`. CF detects the domain is in your account and
   automatically creates a flattened CNAME record on the apex pointing at
   the project.
2. Enter `www.pursueindex.com` as well; it gets a CNAME to apex.
3. Wait for the cert (Let's Encrypt via CF, ~1 min). Status flips to
   "Active."

Verify:

```bash
curl -sI https://pursueindex.com/ | head -3
# → HTTP/2 200 + cf-ray header
```

The `web/public/CNAME` file is a holdover for GitHub Pages. CF Pages
ignores it; harmless. Delete after we disable the GH workflow if you
want a clean tree.

## 4. Wire pursueindex.ai → 301 redirect

In the CF dashboard for `pursueindex.ai`:

1. **DNS** → add a single proxy-only A record on apex:
   - Type: `A`, Name: `@`, IPv4: `192.0.2.1` (placeholder; CF only needs
     the record present so the proxy will service it), Proxy: ON.
   - Same for `www`: `CNAME` → `pursueindex.ai`, Proxy: ON.
2. **Rules** → **Bulk Redirects** → **Create list**:
   - Source: `https://pursueindex.ai/*`
   - Target: `https://pursueindex.com/$1`
   - Status: 301
   - Preserve query string: yes
   - Preserve path suffix: yes
3. Apply the list to a Bulk Redirect rule on the zone.

Verify:

```bash
curl -sI https://pursueindex.ai/some/path?q=1
# → HTTP/2 301 + location: https://pursueindex.com/some/path?q=1
```

Reserve `api.pursueindex.ai` for the future chat backend (see
`.paircoder/plans/chat-interface.md`). Don't wire it now — Workers will
attach to it directly when that lands.

## 5. Update Astro config for production domain

After CF Pages is serving `pursueindex.com`, update `web/astro.config.mjs`:

```js
export default defineConfig({
  site: "https://pursueindex.com",
  base: "/",
  // …
});
```

Push; CF Pages rebuilds. Sitemap and og:url meta will reflect the real
domain.

## 6. Disable the GitHub Pages workflow (when ready)

The `.github/workflows/deploy-ui.yml` workflow still deploys to the
`fantastic-bassoon-…` GH Pages URL on every push. Once CF Pages is the
canonical deploy:

- Option A: delete the workflow file.
- Option B: disable it via repo settings (Actions → Workflows →
  "Deploy UI to GitHub Pages" → Disable).
- Option C: leave it on; it's a free-tier backup. Costs negligible
  CI time per push.

Recommend Option B for ~30 days — leaves us a quick cutover if CF Pages
has an outage during early launch — then delete.

## 7. Sanity checks

- [ ] `pursueindex.com` serves the redesigned UI under HTTPS.
- [ ] `www.pursueindex.com` serves the same.
- [ ] `pursueindex.ai` 301s to `pursueindex.com`.
- [ ] `api.pursueindex.ai` reserved (returns NXDOMAIN or holding page).
- [ ] CF Page Rules: TLS = "Full (strict)", Always Use HTTPS = on,
      Auto Minify off (Astro already minifies).
- [ ] CF Caching: default (let CF Pages handle it; no extra rules
      needed yet).

## 8. Rate-limit + WAF tuning (defer until launch week)

When the chat backend goes live:

- WAF Custom Rule: 30 req/min per IP on `/api/chat` → challenge.
- Bot Fight Mode: ON (Free tier).
- Email obfuscation: OFF (no emails on site).
- Browser Integrity Check: ON.

Don't enable these before launch — they sometimes false-positive and
you don't want a janky pre-launch experience. Flip them on as part of
the production-launch plan checklist.
