// /api/* must be behind the same preview-cookie gate as the homepage.
// Until we flip the gate at launch, anonymous chat requires the cookie.
// These tests pin that contract end-to-end against the default fetch handler.

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

describe("API cookie gate", () => {
  test("/api/retrieve without cookie → 403", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/retrieve", { method: "POST" }),
      envForApi(),
    );
    assert.equal(r.status, 403);
  });

  test("/api/chat without cookie → 403", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/chat", { method: "POST" }),
      envForApi(),
    );
    assert.equal(r.status, 403);
  });

  test("/api/retrieve with cookie reaches the handler (returns 400 on missing query body)", async () => {
    const r = await worker.fetch(
      new Request("https://x/api/retrieve", {
        method: "POST",
        headers: {
          Cookie: "preview=bps-launch",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({}),
      }),
      envForApi(),
    );
    // Past the gate → handler validation; missing query → 400.
    assert.equal(r.status, 400);
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
