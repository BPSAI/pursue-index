// pursue-index Worker entry.
//
// Two jobs:
//   1) Gate the homepage on a preview cookie so the site stays
//      "research preview" until launch. Visitors with no cookie at /
//      get the splash; with the cookie they get the real index.
//   2) Dispatch /api/retrieve and /api/chat to the chat-interface
//      handlers (worker/retrieve.js + worker/chat.js). Both API routes
//      are behind the same preview-cookie gate until launch — better
//      default than letting an API endpoint slip past it.
//
// Magic-link to grant access:
//   https://pursueindex.com/?preview=bps-launch
//   → sets cookie, redirects to /, full site visible thereafter.
//
// To revoke: visit /preview-off (clears cookie).
//
// At launch, drop the gate by either:
//   1) deleting this Worker (revert to static-only assets), or
//   2) inverting the gate logic so / and /api/* serve unconditionally.
//
// Secrets (Worker-side, configured via `wrangler secret put`):
//   VOYAGE_API_KEY      — Voyage embeddings for /api/retrieve query embed.
//   ANTHROPIC_API_KEY   — Anonymous-tier chat. Never leaves the Worker.
// KV namespace bindings:
//   CHAT_KV             — rate limit + semantic cache + daily budget.
//
// CSP is intentionally NOT set here. The card detail pages iframe
// `https://www.war.gov/...` PDFs, so a meaningful CSP needs `frame-src
// https://www.war.gov` plus careful testing against asset previews.

import { handleRetrieve } from "./retrieve.js";
import { handleChat } from "./chat.js";

const PREVIEW_TOKEN = "bps-launch";

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
    "Access-Control-Allow-Headers": "Content-Type, Cookie",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "600",
    Vary: "Origin",
  };
}

export function setCookieHeader(value, maxAgeSeconds) {
  return `preview=${value}; Path=/; Max-Age=${maxAgeSeconds}; Secure; SameSite=Lax; HttpOnly`;
}

/**
 * Parse the Cookie header into a {name: value} map.
 *
 * Cookie format per RFC 6265 §5.4: `name=value; name=value; ...` — any
 * non-` ;` whitespace is technically illegal but we tolerate leading/trailing
 * spaces around names and values to be lenient with proxies. Quoted values
 * are not unquoted; we don't set quoted values anywhere in this Worker.
 */
export function parseCookies(header) {
  const out = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const name = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    if (!name) continue;
    // First occurrence wins — matches browser behavior.
    if (!(name in out)) out[name] = value;
  }
  return out;
}

export function hasPreviewCookie(request) {
  const header = request.headers.get("Cookie") || "";
  const cookies = parseCookies(header);
  return cookies.preview === PREVIEW_TOKEN;
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

    // Magic-link grants access then redirects to /.
    if (url.pathname === "/" && url.searchParams.get("preview") === PREVIEW_TOKEN) {
      return withSecurityHeaders(
        new Response(null, {
          status: 302,
          headers: {
            Location: "/",
            "Set-Cookie": setCookieHeader(PREVIEW_TOKEN, 31536000),
            "Cache-Control": "no-store",
          },
        }),
      );
    }

    // /preview-off clears the cookie.
    if (url.pathname === "/preview-off") {
      return withSecurityHeaders(
        new Response(
          '<!doctype html><meta http-equiv="refresh" content="2;url=/"><p style="font-family:monospace">preview disabled.</p>',
          {
            headers: {
              "Set-Cookie": setCookieHeader("", 0),
              "Content-Type": "text/html; charset=utf-8",
              "Cache-Control": "no-store",
            },
          },
        ),
      );
    }

    // /api/* routes — public after launch; CORS-locked to our origins.
    if (url.pathname.startsWith("/api/")) {
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
      let response;
      if (url.pathname === "/api/retrieve") {
        response = await handleRetrieve(request, env);
      } else if (url.pathname === "/api/chat") {
        response = await handleChat(request, env);
      } else {
        response = new Response(JSON.stringify({ error: "not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      // Stamp CORS headers + security headers and return.
      const corsResponse = new Response(response.body, response);
      for (const [k, v] of Object.entries(corsHeaders(origin))) {
        corsResponse.headers.set(k, v);
      }
      return withSecurityHeaders(corsResponse);
    }

    // Gate is flipped — homepage and every other path serve from static
    // assets unconditionally. The splash route still exists at /splash for
    // anyone who bookmarked it; can be deleted in a follow-up.
    return withSecurityHeaders(await env.ASSETS.fetch(request));
  },
};
