// Post-launch: /api/* is public (CORS-locked but not cookie-gated).
// Pre-launch this suite asserted the cookie gate; that assertion was
// retired the moment we flipped the gate. The CORS lockdown + security
// headers are what now protect the surface.

import { describe, test } from "node:test";
import assert from "node:assert/strict";

import worker from "../index.js";

function makeAssetsBinding() {
  return {
    fetch: async () => new Response("static", { status: 200 }),
  };
}

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

function envForApi() {
  return {
    ASSETS: makeAssetsBinding(),
    CHAT_KV: makeKV(),
    VOYAGE_API_KEY: "v",
    ANTHROPIC_API_KEY: "a",
  };
}

describe("API surface (post-launch)", () => {
  test("/api/retrieve without cookie reaches the handler (no gate)", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/retrieve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }),
      envForApi(),
    );
    // Past the gate (which no longer exists) → handler validation;
    // missing query → 400.
    assert.equal(r.status, 400);
  });

  test("/api/chat without cookie reaches the handler", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }),
      envForApi(),
    );
    assert.equal(r.status, 400);
  });

  test("CORS still rejects foreign Origin", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/retrieve", {
        method: "POST",
        headers: {
          Origin: "https://evil.example.com",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: "test" }),
      }),
      envForApi(),
    );
    assert.equal(r.status, 403);
  });

  test("API responses still carry the security header set", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/retrieve", { method: "POST" }),
      envForApi(),
    );
    assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
    assert.equal(r.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin");
  });
});
