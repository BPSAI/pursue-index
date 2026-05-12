// pursue-index Worker entry.
//
// Dispatches /api/retrieve and /api/chat to the chat-interface handlers
// (worker/retrieve.js + worker/chat.js). All other paths fall through to
// static assets.
//
// Secrets (Worker-side, configured via `wrangler secret put`):
//   VOYAGE_API_KEY      — Voyage embeddings for /api/retrieve query embed.
//   ANTHROPIC_API_KEY   — Anonymous-tier chat. Never leaves the Worker.
// KV namespace bindings:
//   CHAT_KV             — rate limit + semantic cache + daily budget.

import { handleRetrieve } from "./retrieve.js";
import { handleChat } from "./chat.js";
import { tryHandlePdfRoute } from "./pdf.js";

// Allowed origins for /api/* CORS. Same-origin browser requests don't send
// Origin (or send our own host); cross-origin requests from malicious sites
// carry their own Origin, which we reject. Non-browser callers (curl, etc.)
// don't send Origin and pass through.
const ALLOWED_API_ORIGINS = new Set([
  "https://pursueindex.com",
  "https://www.pursueindex.com",
]);

// Worker-handled API endpoints. Anything outside this set with an /api/*
// prefix falls through to the static-asset bundle, so the /api documentation
// page (web/src/pages/api.astro) and any future static /api/* pages serve
// directly from ASSETS.
//
// Source-of-truth contract: the docs page at web/src/pages/api.astro
// describes the surface this set enumerates; keep them in sync. Adding a
// new dynamic Worker route requires adding it here AND documenting it on
// api.astro. Adding a new static /api/* page requires NO Worker change.
//
// Method gating is the handler's job, not the dispatcher's. This allowlist
// is path-only: GET /api/retrieve and GET /api/chat both reach the handler
// and 405 there (worker/retrieve.js:273, worker/chat.js:46).
//
// New entries here REQUIRE a corresponding assertion in
// `scripts/smoke_api_dispatch.sh` so the integration smoke test stays
// comprehensive — that script runs `wrangler dev` in CI and verifies
// the dispatch contract end-to-end, including that paths NOT in this
// set fall through to ASSETS instead of returning the Worker JSON 404.
const WORKER_API_PATHS = new Set(["/api/retrieve", "/api/chat"]);

function corsHeaders(origin) {
  const allowed = origin && ALLOWED_API_ORIGINS.has(origin) ? origin : "https://pursueindex.com";
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  };
}

/**
 * Wrap a Response with a small set of conservative security headers.
 *
 * Intentionally narrow:
 *   - X-Content-Type-Options: nosniff   (kill the IE/Chrome MIME-sniff classes)
 *   - Referrer-Policy: strict-origin-when-cross-origin (default, but explicit)
 *   - X-Frame-Options: SAMEORIGIN       (clickjacking; we never frame ourselves)
 *   - Permissions-Policy: interest-cohort=()  (opt out of FLoC/Topics)
 *   - Content-Security-Policy: a minimum permissive policy. Astro/Preact
 *     hydration scripts inline → script-src 'unsafe-inline'. Tailwind
 *     emits inline styles → style-src 'unsafe-inline'. Card detail iframes
 *     used to embed war.gov PDFs cross-origin (so frame-src had to allow
 *     www.war.gov), but war.gov / Akamai shipped framing protection in
 *     May 2026 and broke that. PDFs are now served same-origin via the
 *     `/pdf/:card_id.pdf` route off R2 (see worker/pdf.js), so frame-src
 *     drops back to 'self' only. img-src keeps www.war.gov for now —
 *     `card.modal_image_url` still points there for non-PDF cards. BYOK
 *     chat calls Anthropic direct → connect-src includes api.anthropic.com.
 *     Tighter than nothing; permissive enough to not break anything.
 *
 *     script-src also includes:
 *       - 'unsafe-eval': required by regl-scatterplot on the /atlas page
 *         (regl compiles WebGL shader programs by Function()-evaluating
 *         generated GLSL → JS strings). Without it the entire 2D atlas
 *         visualization fails to initialize. Acceptable here because all
 *         script sources are same-origin, the request path doesn't accept
 *         user-supplied JS, and `eval` cannot exfiltrate beyond the
 *         existing connect-src allowlist. Site-wide rather than
 *         /atlas-scoped to avoid coupling Worker logic to asset paths.
 *       - https://static.cloudflareinsights.com: Cloudflare's first-party
 *         Web Analytics beacon. Allowing the script source domain is fine;
 *         the beacon itself is a CF service we already trust at the edge.
 *
 *     connect-src also includes:
 *       - https://cloudflareinsights.com: the beacon's RUM telemetry POSTs
 *         go to https://cloudflareinsights.com/cdn-cgi/rum — a different
 *         subdomain than the script host. script-src governs the script
 *         load, connect-src governs the egress; both are needed or the
 *         second CSP violation reappears on a different directive.
 *
 * If the underlying response already set one of these (e.g. an asset that
 * needs to be framed), defer to it — we use `headers.has()` not `set()`.
 */
const CSP_VALUE = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://static.cloudflareinsights.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' https://www.war.gov data:",
  "font-src 'self' data:",
  // DVIDS embed player for VID cards (operator-noted 2026-05-12: VID
  // cards have no asset_url, so playback uses the DVIDS public embed
  // iframe — same source the war.gov upstream display uses). DVIDS is
  // a DoD-operated public-affairs distribution hub; the embed player
  // serves the same media file the card_id's dvids_video_id resolves
  // to. Adding to frame-src so the iframe is permitted; falls back to
  // an "Open on DVIDS ↗" link if the embed iframe is ever broken or
  // blocked by the DVIDS side.
  "frame-src 'self' https://www.dvidshub.net",
  "connect-src 'self' https://api.anthropic.com https://api.voyageai.com https://cloudflareinsights.com",
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  // Explicit `object-src 'none'` added 2026-05-12 (laverna SEC-002)
  // after the PDF iframe sandbox was dropped for Chrome 147 PDFium
  // compatibility (commit 4e03a1d). default-src 'self' covered this
  // as a fallback, but locking it explicitly to 'none' means a
  // future CSP refactor of `default-src` can't silently re-open the
  // `<object>` / `<embed>` plugin path. The unsandboxed iframe now
  // inherits the site CSP, so even a script-injecting PDF can't
  // pivot to plugin-based payload delivery.
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  ["X-Content-Type-Options", "nosniff"],
  ["Referrer-Policy", "strict-origin-when-cross-origin"],
  ["X-Frame-Options", "SAMEORIGIN"],
  ["Permissions-Policy", "interest-cohort=()"],
  ["Content-Security-Policy", CSP_VALUE],
  // HSTS: 1 year, subdomains opt-in. `preload` deliberately omitted —
  // adding it commits us to the Chromium HSTS preload list, which is
  // effectively irreversible. We can add `preload` and submit later
  // once we're confident every subdomain we'll ever want to serve is
  // HTTPS-only.
  ["Strict-Transport-Security", "max-age=31536000; includeSubDomains"],
];

export function withSecurityHeaders(response) {
  // Response.headers is immutable on the original; clone via the constructor.
  const next = new Response(response.body, response);
  for (const [name, value] of SECURITY_HEADERS) {
    if (!next.headers.has(name)) next.headers.set(name, value);
  }
  return next;
}

export default {
  async fetch(request, env) {
    // `new URL(request.url).pathname` is normalized by the URL parser —
    // sequences like `/api/../etc/passwd` resolve to `/etc/passwd` before
    // we test set membership. The fall-through ASSETS binding is bound to
    // the static build artifact (a flat, bounded file tree), so even if a
    // crafted path somehow slipped past the dispatcher there is no
    // server-side filesystem to traverse. Defense-in-depth posture, not a
    // load-bearing check. (laverna PR #16 informational finding.)
    const url = new URL(request.url);

    if (WORKER_API_PATHS.has(url.pathname)) {
      // CORS: only browsers from our own origins should be calling these.
      // Same-origin requests don't send Origin (or send our own host); cross-
      // origin requests from a malicious site would carry a different Origin.
      const origin = request.headers.get("Origin");
      if (origin && !ALLOWED_API_ORIGINS.has(origin)) {
        return withSecurityHeaders(
          new Response(
            JSON.stringify({ error: "cross-origin not allowed" }),
            {
              status: 403,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      // Preflight OPTIONS — short-circuit with the CORS headers.
      if (request.method === "OPTIONS") {
        return withSecurityHeaders(
          new Response(null, {
            status: 204,
            headers: corsHeaders(origin),
          }),
        );
      }
      const response = url.pathname === "/api/retrieve"
        ? await handleRetrieve(request, env)
        : await handleChat(request, env);
      // Stamp CORS headers + security headers and return.
      const corsResponse = new Response(response.body, response);
      for (const [k, v] of Object.entries(corsHeaders(origin))) {
        corsResponse.headers.set(k, v);
      }
      return withSecurityHeaders(corsResponse);
    }

    // Self-hosted PDF route. PDFs live in R2 (`PDFS` binding) so the
    // card-detail iframe can serve them same-origin — war.gov ships
    // framing protection that blocks the cross-origin embed. See
    // worker/pdf.js for the full contract. Returns null when the
    // request isn't a PDF GET, so we fall through to ASSETS below.
    const pdfResponse = await tryHandlePdfRoute(request, env);
    if (pdfResponse) return withSecurityHeaders(pdfResponse);

    // Everything else falls through to static assets — including the
    // /api documentation page and any other /api/* paths a future
    // static page might add.
    return withSecurityHeaders(await env.ASSETS.fetch(request));
  },
};
