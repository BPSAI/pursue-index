// Tests for the cache-header wrapper.
//
// Sprint 2.1 (2026-05-17): `web/public/_headers` was dead weight because
// Workers Static Assets with `run_worker_first: true` doesn't apply the
// _headers file — the Worker handles every request first and the ASSETS
// binding's response doesn't carry the directives through. Verified at
// deploy: `/_astro/*` was returning `max-age=0, must-revalidate` instead
// of the `max-age=31536000, immutable` declared in _headers. APAC LCP
// stayed at 12-13s because regional edges didn't honor the intended TTL.
//
// Fix: own Cache-Control in the Worker. Single source of truth, version-
// controlled, code-reviewable. These tests pin the path-to-policy table
// so a future regression that drops or weakens a TTL bucket fails CI.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import worker, { withCacheHeaders } from "../index.js";

/**
 * Drive the full Worker dispatcher with an ASSETS stub. The cache-header
 * wrapper is wired at the ASSETS fall-through point, so end-to-end checks
 * exercise the production code path rather than the helper in isolation.
 */
function makeKV() {
  const store = new Map();
  return {
    async get(key, type) {
      const raw = store.get(key);
      if (raw == null) return null;
      if (type === "json") return JSON.parse(raw);
      return raw;
    },
    async put(key, value) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

function envWithAssets() {
  return {
    ASSETS: {
      fetch: async () => new Response("asset", { status: 200 }),
    },
    CHAT_KV: makeKV(),
    VOYAGE_API_KEY: "v",
    ANTHROPIC_API_KEY: "a",
  };
}

async function fetchPath(path) {
  return worker.fetch(
    new Request(`https://pursueindex.com${path}`, { method: "GET" }),
    envWithAssets(),
  );
}

describe("withCacheHeaders — unit", () => {
  test("hashed Astro asset gets one-year immutable", () => {
    const r = withCacheHeaders(
      new Response("css"),
      new Request("https://pursueindex.com/_astro/Foo.abc123.css"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=31536000, immutable",
    );
  });

  test("data JSON gets 1h fresh + 24h SWR", () => {
    const r = withCacheHeaders(
      new Response("{}"),
      new Request("https://pursueindex.com/data/pages.json"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=3600, stale-while-revalidate=86400",
    );
  });

  test("embeddings blob gets the same SWR policy as data JSON", () => {
    const r = withCacheHeaders(
      new Response("bin"),
      new Request("https://pursueindex.com/data/embeddings.bin"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=3600, stale-while-revalidate=86400",
    );
  });

  test("thumbnail image gets 1-week fresh + 30-day SWR", () => {
    const r = withCacheHeaders(
      new Response("img"),
      new Request("https://pursueindex.com/data/thumbs/xyz.webp"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=604800, stale-while-revalidate=2592000",
    );
  });

  test("OG card image gets 1-week fresh + 30-day SWR", () => {
    const r = withCacheHeaders(
      new Response("img"),
      new Request("https://pursueindex.com/og/abc.png"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=604800, stale-while-revalidate=2592000",
    );
  });

  test("llms.txt GEO surface gets 1-hour TTL", () => {
    const r = withCacheHeaders(
      new Response("..."),
      new Request("https://pursueindex.com/llms.txt"),
    );
    assert.equal(r.headers.get("Cache-Control"), "public, max-age=3600");
  });

  test("llms-full.txt GEO surface gets 1-hour TTL", () => {
    const r = withCacheHeaders(
      new Response("..."),
      new Request("https://pursueindex.com/llms-full.txt"),
    );
    assert.equal(r.headers.get("Cache-Control"), "public, max-age=3600");
  });

  test("robots.txt GEO surface gets 1-hour TTL", () => {
    const r = withCacheHeaders(
      new Response("..."),
      new Request("https://pursueindex.com/robots.txt"),
    );
    assert.equal(r.headers.get("Cache-Control"), "public, max-age=3600");
  });

  test("sitemap-index.xml gets 1-hour TTL", () => {
    const r = withCacheHeaders(
      new Response("<?xml ?>"),
      new Request("https://pursueindex.com/sitemap.xml"),
    );
    assert.equal(r.headers.get("Cache-Control"), "public, max-age=3600");
  });

  test("unmatched path passes through unchanged (no Cache-Control set)", () => {
    const r = withCacheHeaders(
      new Response("html"),
      new Request("https://pursueindex.com/unknown.html"),
    );
    assert.equal(r.headers.get("Cache-Control"), null);
  });

  test("meaningful upstream Cache-Control is preserved", () => {
    // Card-detail HTML or chat-stream response may already carry a
    // specific Cache-Control (e.g. `private, no-store` for SSE). Never
    // override a deliberate upstream choice.
    const r = withCacheHeaders(
      new Response("data", {
        headers: { "Cache-Control": "private, no-store" },
      }),
      new Request("https://pursueindex.com/_astro/Foo.abc123.css"),
    );
    assert.equal(r.headers.get("Cache-Control"), "private, no-store");
  });

  test("default placeholder Cache-Control is replaced when a policy matches", () => {
    // The ASSETS binding's default is `public, max-age=0, must-revalidate`
    // — that is exactly the "no opinion" signal we override. Anything
    // else is treated as an upstream opinion (see test above).
    const r = withCacheHeaders(
      new Response("css", {
        headers: { "Cache-Control": "public, max-age=0, must-revalidate" },
      }),
      new Request("https://pursueindex.com/_astro/Foo.abc123.css"),
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=31536000, immutable",
    );
  });
});

describe("withCacheHeaders — wired into the dispatcher", () => {
  test("/_astro/* asset response carries the long-cache directive", async () => {
    const r = await fetchPath("/_astro/Foo.abc123.css");
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=31536000, immutable",
    );
  });

  test("/data/pages.json carries the SWR directive", async () => {
    const r = await fetchPath("/data/pages.json");
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=3600, stale-while-revalidate=86400",
    );
  });

  test("ASSETS responses still carry the security header set", async () => {
    // Regression: a future refactor that drops withSecurityHeaders from
    // the ASSETS fall-through (or reorders the wrappers) must fail CI.
    // Cache headers are layered ON TOP OF, not INSTEAD OF, security.
    const r = await fetchPath("/_astro/Foo.abc123.css");
    assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
    assert.equal(
      r.headers.get("Referrer-Policy"),
      "strict-origin-when-cross-origin",
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=31536000, immutable",
    );
  });

  test("unmatched HTML path falls through with neither cache directive nor breakage", async () => {
    const r = await fetchPath("/some-card-detail-page");
    assert.equal(r.status, 200);
    // Security headers still applied …
    assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
    // … but Cache-Control is left untouched (no policy match).
    assert.equal(r.headers.get("Cache-Control"), null);
  });
});
