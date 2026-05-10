// Tests for the self-hosted PDF route GET /pdf/:card_id.pdf.
//
// Background: war.gov / Akamai added cross-origin framing protection in
// May 2026, so the card-detail iframe could no longer embed war.gov PDFs
// directly (Chrome surfaced the embed as `chrome-error://chromewebdata/`).
// We mirrored the corpus into the Cloudflare R2 bucket `pursue-pdfs`
// (binding name `PDFS`, key format `<card_id>.pdf`) and now serve them
// from a same-origin Worker route. The OPEN ↗ button on the card page
// still points at war.gov (cite-of-record).

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import worker from "../index.js";

/** A canonical 16-char hex card_id used across tests. */
const VALID_CARD_ID = "abcdef0123456789";

/**
 * Build a stub R2 binding whose `get(key, opts)` returns the configured
 * object (or null). Captures the (key, opts) the Worker passed in so the
 * tests can assert range plumbing.
 */
function makeR2(objectsByKey) {
  const calls = [];
  return {
    calls,
    async get(key, opts) {
      calls.push({ key, opts });
      const entry = objectsByKey[key];
      if (entry == null) return null;
      return entry;
    },
  };
}

/** Build a minimal R2Object-shaped value with a `body` ReadableStream. */
function r2Object({ body, size, etag = '"abc123"', range }) {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(body);
      controller.close();
    },
  });
  return {
    body: stream,
    size,
    etag,
    httpEtag: etag,
    range, // present on partial-response objects (R2 returns it for ranged gets)
  };
}

function envWith(r2) {
  return {
    PDFS: r2,
    ASSETS: { fetch: async () => new Response("static", { status: 404 }) },
    CHAT_KV: { get: async () => null, put: async () => {}, delete: async () => {} },
    VOYAGE_API_KEY: "v",
    ANTHROPIC_API_KEY: "a",
  };
}

describe("GET /pdf/:card_id.pdf", () => {
  test("rejects a non-hex card_id with 400 text/plain", async () => {
    const r2 = makeR2({});
    const r = await worker.fetch(
      new Request("https://x/pdf/notahex.pdf", { method: "GET" }),
      envWith(r2),
    );
    assert.equal(r.status, 400);
    assert.equal(r.headers.get("Content-Type"), "text/plain");
    assert.equal(await r.text(), "invalid card_id");
    // Validation must happen before any R2 round-trip.
    assert.equal(r2.calls.length, 0);
  });

  test("rejects a card_id of the wrong length with 400", async () => {
    // 15 hex chars — one too few.
    const r2 = makeR2({});
    const r = await worker.fetch(
      new Request("https://x/pdf/abcdef012345678.pdf", { method: "GET" }),
      envWith(r2),
    );
    assert.equal(r.status, 400);
    assert.equal(r2.calls.length, 0);
  });

  test("rejects an uppercase-hex card_id with 400 (lowercase only)", async () => {
    // Card IDs are derived as `sha256(...)[:16]` and stored lowercase.
    // Accepting uppercase here would let two URLs serve the same object
    // and confuse the immutable cache.
    const r2 = makeR2({});
    const r = await worker.fetch(
      new Request("https://x/pdf/ABCDEF0123456789.pdf", { method: "GET" }),
      envWith(r2),
    );
    assert.equal(r.status, 400);
    assert.equal(r2.calls.length, 0);
  });

  test("returns 404 text/plain when R2 has no object for that card_id", async () => {
    const r2 = makeR2({}); // empty bucket
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, { method: "GET" }),
      envWith(r2),
    );
    assert.equal(r.status, 404);
    assert.equal(r.headers.get("Content-Type"), "text/plain");
    assert.equal(await r.text(), "PDF not found");
    // Round-trip happened with the canonical key.
    assert.deepEqual(r2.calls, [{ key: `${VALID_CARD_ID}.pdf`, opts: undefined }]);
  });

  test("happy path: 200 streams body with PDF + cache + range headers", async () => {
    const body = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"
    const r2 = makeR2({
      [`${VALID_CARD_ID}.pdf`]: r2Object({ body, size: body.byteLength, etag: '"deadbeef"' }),
    });
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, { method: "GET" }),
      envWith(r2),
    );
    assert.equal(r.status, 200);
    assert.equal(r.headers.get("Content-Type"), "application/pdf");
    assert.equal(
      r.headers.get("Content-Disposition"),
      `inline; filename="${VALID_CARD_ID}.pdf"`,
    );
    assert.equal(
      r.headers.get("Cache-Control"),
      "public, max-age=31536000, immutable",
    );
    assert.equal(r.headers.get("Accept-Ranges"), "bytes");
    assert.equal(r.headers.get("Content-Length"), String(body.byteLength));
    assert.equal(r.headers.get("ETag"), '"deadbeef"');
    // Security headers still flow.
    assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
    // Body is the streamed object body.
    const buf = new Uint8Array(await r.arrayBuffer());
    assert.deepEqual(Array.from(buf), Array.from(body));
  });

  test("non-GET method falls through to ASSETS (route is GET-only)", async () => {
    // POST/PUT/DELETE on this path shouldn't hit the R2 handler — they
    // should fall through to ASSETS, which will 404 in production. We
    // assert on R2 not being called; the ASSETS stub here returns 404.
    const r2 = makeR2({});
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, { method: "POST" }),
      envWith(r2),
    );
    assert.equal(r2.calls.length, 0);
    assert.equal(r.status, 404); // from ASSETS stub
  });

  test("Range: bytes=0-99 returns 206 with Content-Range and the partial body", async () => {
    const full = new Uint8Array(1000);
    for (let i = 0; i < full.length; i++) full[i] = i & 0xff;
    const partial = full.slice(0, 100);
    // R2 returns just the partial bytes when given a range opt; mirror that.
    const r2 = {
      calls: [],
      async get(key, opts) {
        this.calls.push({ key, opts });
        return {
          body: new ReadableStream({
            start(c) { c.enqueue(partial); c.close(); },
          }),
          size: full.byteLength,
          etag: '"r"',
          httpEtag: '"r"',
          range: { offset: 0, length: 100 },
        };
      },
    };
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "bytes=0-99" },
      }),
      envWith(r2),
    );
    assert.equal(r.status, 206);
    assert.equal(r.headers.get("Content-Range"), `bytes 0-99/${full.byteLength}`);
    assert.equal(r.headers.get("Content-Length"), "100");
    assert.equal(r.headers.get("Accept-Ranges"), "bytes");
    // R2 was asked for the right range.
    assert.deepEqual(r2.calls[0].opts, { range: { offset: 0, length: 100 } });
    const buf = new Uint8Array(await r.arrayBuffer());
    assert.equal(buf.byteLength, 100);
  });

  test("Range: bytes=500- (open-ended) requests offset only", async () => {
    const fullSize = 1000;
    const tail = new Uint8Array(500);
    const r2 = {
      calls: [],
      async get(key, opts) {
        this.calls.push({ key, opts });
        return {
          body: new ReadableStream({
            start(c) { c.enqueue(tail); c.close(); },
          }),
          size: fullSize,
          etag: '"r"',
          httpEtag: '"r"',
          range: { offset: 500, length: 500 },
        };
      },
    };
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "bytes=500-" },
      }),
      envWith(r2),
    );
    assert.equal(r.status, 206);
    assert.equal(r.headers.get("Content-Range"), `bytes 500-999/${fullSize}`);
    // For an open-ended range, the offset is set; length is omitted so R2
    // streams to EOF. This contract matches Cloudflare's R2GetOptions docs.
    assert.equal(r2.calls[0].opts.range.offset, 500);
    assert.equal(r2.calls[0].opts.range.length, undefined);
  });

  test("Range whose offset is past EOF returns 416 with Content-Range: bytes */<size>", async () => {
    // RFC 9110 §15.5.17: an unsatisfiable range MUST yield 416 with a
    // `Content-Range: bytes */<complete-length>` so clients can recompute.
    // The previous implementation served 206 with `bytes 999999--900000/100`,
    // a malformed header that crashed strict clients (and PDF.js viewers
    // would silently retry with a full GET, masking the bug). We detect
    // offset >= obj.size after the R2 round-trip — no second fetch needed
    // because R2 already gave us the size.
    const fullSize = 100;
    const r2 = {
      calls: [],
      async get(key, opts) {
        this.calls.push({ key, opts });
        // R2 returns the object even when the requested range is unsatisfiable;
        // the worker is responsible for clamping. In practice R2 clamps too,
        // but we don't rely on its clamping for the 416 decision — we look at
        // the offset we asked for vs. obj.size, which is always correct.
        return {
          body: new ReadableStream({ start(c) { c.close(); } }),
          size: fullSize,
          etag: '"r"',
          httpEtag: '"r"',
          range: { offset: 999999, length: 0 },
        };
      },
    };
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "bytes=999999-" },
      }),
      envWith(r2),
    );
    assert.equal(r.status, 416);
    assert.equal(r.headers.get("Content-Range"), `bytes */${fullSize}`);
    assert.equal(r.headers.get("Content-Type"), "text/plain");
    assert.equal(await r.text(), "range not satisfiable");
  });

  test("Range: bytes=-100 (suffix range, unsupported syntax) falls back to full 200", async () => {
    // Suffix-range syntax (`bytes=-N` = "last N bytes") is part of RFC 9110
    // but PDF.js never emits it. Our parser refuses anything that isn't
    // `bytes=N-` or `bytes=N-M`. Falling back to a full 200 (rather than
    // 416-ing) matches nginx/CloudFront and keeps unfamiliar clients alive.
    const body = new Uint8Array([1, 2, 3]);
    const r2 = makeR2({
      [`${VALID_CARD_ID}.pdf`]: r2Object({ body, size: 3, etag: '"e"' }),
    });
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "bytes=-100" },
      }),
      envWith(r2),
    );
    assert.equal(r.status, 200);
    assert.equal(r2.calls[0].opts, undefined);
  });

  test("Range with multiple ranges (multi-range) falls back to full 200", async () => {
    // Multi-range responses require `multipart/byteranges`, which is more
    // complexity than this handler's budget allows (PDF.js never uses it).
    // The parser refuses, callers see a full 200.
    const body = new Uint8Array([1, 2, 3]);
    const r2 = makeR2({
      [`${VALID_CARD_ID}.pdf`]: r2Object({ body, size: 3, etag: '"e"' }),
    });
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "bytes=0-99,200-299" },
      }),
      envWith(r2),
    );
    assert.equal(r.status, 200);
    assert.equal(r2.calls[0].opts, undefined);
  });

  test("HEAD: same headers as GET, but no body", async () => {
    // HEAD must report Content-Length, ETag, Accept-Ranges identically to
    // GET so caching middleboxes can size the entity without fetching it.
    // PDF.js doesn't issue HEAD, but curl -I and CDN warmers do, and a
    // 404-on-HEAD would mislead any operator probing the surface.
    const body = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    const r2 = makeR2({
      [`${VALID_CARD_ID}.pdf`]: r2Object({ body, size: body.byteLength, etag: '"h"' }),
    });
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, { method: "HEAD" }),
      envWith(r2),
    );
    assert.equal(r.status, 200);
    assert.equal(r.headers.get("Content-Type"), "application/pdf");
    assert.equal(r.headers.get("Content-Length"), String(body.byteLength));
    assert.equal(r.headers.get("ETag"), '"h"');
    assert.equal(r.headers.get("Accept-Ranges"), "bytes");
    // HEAD body must be empty.
    const buf = new Uint8Array(await r.arrayBuffer());
    assert.equal(buf.byteLength, 0);
  });

  test("HEAD on a missing object returns 404 (not fall-through)", async () => {
    // The HEAD path must be the same dispatcher branch as GET, so a missing
    // R2 object 404s here rather than falling through to ASSETS (which
    // would also 404, but with the wrong Content-Type and a misleading
    // server-side log line).
    const r2 = makeR2({});
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, { method: "HEAD" }),
      envWith(r2),
    );
    assert.equal(r.status, 404);
    // R2 was actually consulted — proving HEAD reached our handler.
    assert.equal(r2.calls.length, 1);
  });

  test("malformed Range header is ignored (treated as full GET, 200)", async () => {
    // Defense-in-depth: a malformed `Range: garbage` header shouldn't
    // 416 the user, just fall back to a full body. Cheap to implement;
    // matches how nginx and most CDNs behave.
    const body = new Uint8Array([1, 2, 3]);
    const r2 = makeR2({
      [`${VALID_CARD_ID}.pdf`]: r2Object({ body, size: 3, etag: '"e"' }),
    });
    const r = await worker.fetch(
      new Request(`https://x/pdf/${VALID_CARD_ID}.pdf`, {
        method: "GET",
        headers: { Range: "rows=0-99" }, // not bytes=
      }),
      envWith(r2),
    );
    assert.equal(r.status, 200);
    // R2 was called WITHOUT a range option, since we couldn't parse one.
    assert.equal(r2.calls[0].opts, undefined);
  });
});
