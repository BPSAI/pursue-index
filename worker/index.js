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
// At launch, drop the gate by either:
//   1) deleting this Worker (revert to static-only assets), or
//   2) inverting the gate logic so / serves the index unconditionally.

const PREVIEW_COOKIE_VALUE = "preview=bps-launch";
const PREVIEW_TOKEN = "bps-launch";

function setCookieHeader(value, maxAgeSeconds) {
  return `preview=${value}; Path=/; Max-Age=${maxAgeSeconds}; Secure; SameSite=Lax; HttpOnly`;
}

function hasPreviewCookie(request) {
  const cookie = request.headers.get("Cookie") || "";
  return cookie.includes(PREVIEW_COOKIE_VALUE);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Magic-link grants access then redirects to /.
    if (url.pathname === "/" && url.searchParams.get("preview") === PREVIEW_TOKEN) {
      return new Response(null, {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie": setCookieHeader(PREVIEW_TOKEN, 31536000),
          "Cache-Control": "no-store",
        },
      });
    }

    // /preview-off clears the cookie.
    if (url.pathname === "/preview-off") {
      return new Response(
        '<!doctype html><meta http-equiv="refresh" content="2;url=/"><p style="font-family:monospace">preview disabled.</p>',
        {
          headers: {
            "Set-Cookie": setCookieHeader("", 0),
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
          },
        },
      );
    }

    // Gate the homepage. Every other path falls through to static assets.
    if (url.pathname === "/" || url.pathname === "") {
      if (!hasPreviewCookie(request)) {
        const splashUrl = new URL("/splash", url);
        return env.ASSETS.fetch(new Request(splashUrl, request));
      }
    }

    return env.ASSETS.fetch(request);
  },
};
