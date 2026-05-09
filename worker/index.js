// pursue-index Worker entry.
//
// Currently does one job: gate the homepage on a preview cookie so the site
// stays "research preview" until launch. Visitors with no preview cookie
// hitting / get the splash page. Visitors with the cookie get the real index.
// Every other route serves the static site as-is.
//
// Magic-link to grant access:
//   https://pursueindex.com/?preview=bps-launch
//   → sets cookie, redirects to /, full site visible thereafter.
//
// To revoke: visit /preview-off (clears cookie).
//
// Future chat surface (`/api/chat` etc.): the cookie gate is *also* expected
// to apply to those routes once they ship. Treat the splash cookie as
// "preview access" full-stop until launch — better default than letting an
// API endpoint slip past the gate. This is enforced by the gate-everything
// branch below.
//
// At launch, drop the gate by either:
//   1) deleting this Worker (revert to static-only assets), or
//   2) inverting the gate logic so / serves the index unconditionally.
//
// CSP is intentionally NOT set here. The card detail pages iframe
// `https://www.war.gov/...` PDFs, so a meaningful CSP needs `frame-src
// https://www.war.gov` plus careful testing against asset previews. The
// chat-interface plan picks that up.

const PREVIEW_TOKEN = "bps-launch";

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
 *
 * If the underlying response already set one of these (e.g. an asset that
 * needs to be framed), defer to it — we use `headers.has()` not `set()`.
 * No CSP — see header note above.
 */
const SECURITY_HEADERS = [
  ["X-Content-Type-Options", "nosniff"],
  ["Referrer-Policy", "strict-origin-when-cross-origin"],
  ["X-Frame-Options", "SAMEORIGIN"],
  ["Permissions-Policy", "interest-cohort=()"],
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

    // Gate the homepage. Every other path falls through to static assets.
    if (url.pathname === "/" || url.pathname === "") {
      if (!hasPreviewCookie(request)) {
        // /splash/ with trailing slash matches Astro's auto-trailing-slash
        // build output (web/dist/splash/index.html). Without the slash CF
        // returns a 307, which we'd then have to follow.
        const splashUrl = new URL("/splash/", url);
        return withSecurityHeaders(
          await env.ASSETS.fetch(new Request(splashUrl, request)),
        );
      }
    }

    return withSecurityHeaders(await env.ASSETS.fetch(request));
  },
};
