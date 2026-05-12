// End-to-end tests for the alias resolver wired into the worker dispatcher.
//
// Verifies that:
//   - /card/<old_id> → 301 with Location: /card/<new_id> when alias exists
//   - /card/<known_id_in_manifest> falls through to ASSETS (no redirect)
//   - /pdf/<old_id>.pdf serves the preserved bytes AND stamps the
//     X-Pursue-Aliased-To header
//   - /pdf/<known_id>.pdf serves without the alias header
//   - A corrupt or missing card-aliases.json never takes down non-aliased
//     requests
//   - Security headers still apply to alias redirects

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import worker from "../index.js";

const OLD_ID = "aa3097b4c549a67a";
const NEW_ID = "9e2c2621d67dde12";
const MANIFEST_ID = "abcdef0123456789"; // not in aliases — should fall through
const PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"

/** Build an env stub whose ASSETS.fetch returns the configured payload. */
function envWith({ aliases = { aliases: [] }, assetStatus = 200, pdfStatus = 200 } = {}) {
  return {
    ASSETS: {
      async fetch(req) {
        const url = new URL(typeof req === "string" ? req : req.url);
        if (url.pathname === "/data/card-aliases.json") {
          if (aliases === null) {
            return new Response("not found", { status: 404 });
          }
          if (typeof aliases === "string") {
            // Allow tests to inject corrupt JSON.
            return new Response(aliases, { status: 200, headers: { "Content-Type": "application/json" } });
          }
          return new Response(JSON.stringify(aliases), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("static asset body", { status: assetStatus });
      },
    },
    PDFS: {
      async get(key) {
        if (pdfStatus === 404) return null;
        return {
          body: new ReadableStream({
            start(c) {
              c.enqueue(PDF_BYTES);
              c.close();
            },
          }),
          size: PDF_BYTES.length,
          httpEtag: '"fakeetag"',
        };
      },
      async head(key) {
        if (pdfStatus === 404) return null;
        return { size: PDF_BYTES.length, httpEtag: '"fakeetag"' };
      },
    },
  };
}

describe("worker alias dispatch", () => {
  test("GET /card/<aliased_old_id> → 301 → /card/<new_id>", async () => {
    const env = envWith({
      aliases: {
        aliases: [
          {
            old_card_id: OLD_ID,
            new_card_id: NEW_ID,
            established: "2026-05-12T19:30:00Z",
            method: "byte_collision",
          },
        ],
      },
    });
    const resp = await worker.fetch(new Request(`https://example.com/card/${OLD_ID}`), env);
    assert.equal(resp.status, 301);
    assert.equal(resp.headers.get("Location"), `/card/${NEW_ID}`);
    assert.equal(resp.headers.get("X-Pursue-Aliased-From"), OLD_ID);
    // Security headers still apply.
    assert.ok(resp.headers.get("Content-Security-Policy"), "expected CSP on redirect");
  });

  test("GET /card/<not_aliased_id> falls through to ASSETS (no redirect)", async () => {
    const env = envWith({
      aliases: {
        aliases: [
          { old_card_id: OLD_ID, new_card_id: NEW_ID, method: "byte_collision" },
        ],
      },
    });
    const resp = await worker.fetch(new Request(`https://example.com/card/${MANIFEST_ID}`), env);
    assert.equal(resp.status, 200);
    assert.equal(await resp.text(), "static asset body");
  });

  test("GET /pdf/<aliased_old_id>.pdf serves bytes + X-Pursue-Aliased-To header", async () => {
    const env = envWith({
      aliases: {
        aliases: [
          { old_card_id: OLD_ID, new_card_id: NEW_ID, method: "byte_collision" },
        ],
      },
    });
    const resp = await worker.fetch(new Request(`https://example.com/pdf/${OLD_ID}.pdf`), env);
    assert.equal(resp.status, 200);
    assert.equal(resp.headers.get("X-Pursue-Aliased-To"), NEW_ID);
    assert.equal(resp.headers.get("Content-Type"), "application/pdf");
  });

  test("GET /pdf/<not_aliased>.pdf has no X-Pursue-Aliased-To header", async () => {
    const env = envWith({
      aliases: { aliases: [] },
    });
    const resp = await worker.fetch(new Request(`https://example.com/pdf/${MANIFEST_ID}.pdf`), env);
    assert.equal(resp.status, 200);
    assert.equal(resp.headers.get("X-Pursue-Aliased-To"), null);
  });

  test("corrupt card-aliases.json does not break non-aliased requests", async () => {
    const env = envWith({ aliases: "this is not JSON" });
    const resp = await worker.fetch(new Request(`https://example.com/card/${MANIFEST_ID}`), env);
    assert.equal(resp.status, 200);
    assert.equal(await resp.text(), "static asset body");
  });

  test("missing card-aliases.json does not break non-aliased requests", async () => {
    const env = envWith({ aliases: null });
    const resp = await worker.fetch(new Request(`https://example.com/card/${MANIFEST_ID}`), env);
    assert.equal(resp.status, 200);
  });

  test("aliased redirect preserves trailing slash", async () => {
    const env = envWith({
      aliases: {
        aliases: [{ old_card_id: OLD_ID, new_card_id: NEW_ID, method: "byte_collision" }],
      },
    });
    const resp = await worker.fetch(new Request(`https://example.com/card/${OLD_ID}/`), env);
    assert.equal(resp.status, 301);
    assert.equal(resp.headers.get("Location"), `/card/${NEW_ID}/`);
  });

  test("aliases with operator_revoke as latest entry are not followed", async () => {
    const env = envWith({
      aliases: {
        aliases: [
          { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-01-01", method: "byte_collision" },
          { old_card_id: OLD_ID, new_card_id: NEW_ID, established: "2026-02-01", method: "operator_revoke" },
        ],
      },
    });
    const resp = await worker.fetch(new Request(`https://example.com/card/${OLD_ID}`), env);
    // Not a 301 — falls through to ASSETS which 200s with the stub body.
    assert.equal(resp.status, 200);
    assert.equal(await resp.text(), "static asset body");
  });
});
