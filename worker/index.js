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

// Allowed origins for /api/* CORS. Same-origin browser requests don't send
// Origin (or send our own host); cross-origin requests from malicious sites
// carry their own Origin, which we reject. Non-browser callers (curl, etc.)
// don't send Origin and pass through.
const ALLOWED_API_ORIGINS = new Set([
  "https://pursueindex.com",
  "https://www.pursueindex.com",
]);

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
 *     war.gov PDFs → frame-src + img-src include www.war.gov. BYOK chat
 *     calls Anthropic direct → connect-src includes api.anthropic.com.
 *     Tighter than nothing; permissive enough to not break anything.
 *
 * If the underlying response already set one of these (e.g. an asset that
 * needs to be framed), defer to it — we use `headers.has()` not `set()`.
 */
const CSP_VALUE = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' https://www.war.gov data:",
  "font-src 'self' data:",
  "frame-src 'self' https://www.war.gov",
  "connect-src 'self' https://api.anthropic.com https://api.voyageai.com",
  "frame-ancestors 'self'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = [
  ["X-Content-Type-Options", "nosniff"],
  ["Referrer-Policy", "strict-origin-when-cross-origin"],
  ["X-Frame-Options", "SAMEORIGIN"],
  ["Permissions-Policy", "interest-cohort=()"],
  ["Content-Security-Policy", CSP_VALUE],
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
    const url = new URL(request.url);

    // Worker-handled API endpoints. Anything outside this set with an
    // /api/* prefix falls through to the static-asset bundle so the
    // /api documentation page (web/src/pages/api.astro) actually serves.
    const WORKER_API_PATHS = new Set(["/api/retrieve", "/api/chat"]);

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

    // Everything else falls through to static assets — including the
    // /api documentation page and any other /api/* paths a future
    // static page might add.
    return withSecurityHeaders(await env.ASSETS.fetch(request));
  },
};
