// Integration test for handleChat: rate limit, cache, budget, SSE proxy.
//
// Strategy: mock everything (KV, ASSETS, embedFn, Anthropic fetch) and
// drive the handler end-to-end. We assert on outgoing requests, response
// headers, and the SSE bytes piped through to the client.

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { handleChat } from "../chat.js";
import { _resetCaches } from "../retrieve.js";
import { RATE_LIMIT, DAILY_BUDGET_USD } from "../chat_kv.js";
import {
  anthropicSSEResponse,
  anthropicSSEMovedUsageResponse,
} from "./fixtures/anthropic_sse.js";

function makeKV() {
  const store = new Map();
  return {
    _store: store,
    async get(key, type) {
      const raw = store.get(key);
      if (raw == null) return null;
      if (type === "json") return JSON.parse(raw);
      return raw;
    },
    async put(key, value, _opts) {
      store.set(key, value);
    },
    async delete(key) {
      store.delete(key);
    },
  };
}

function makeAssetsEnv() {
  // One-passage corpus.
  const u16 = new Uint16Array([
    floatToHalf(1),
    floatToHalf(0),
    floatToHalf(0),
  ]);
  const indexJson = {
    model_id: "voyage-3",
    dim: 3,
    n: 1,
    pages: [["card-a", 1]],
  };
  const pagesArr = [
    {
      id: "card-a-p1",
      card_id: "card-a",
      page: 1,
      title: "Test card",
      text: "The quick brown fox jumped over the lazy dog. Roswell incident details.",
    },
  ];
  return {
    ASSETS: {
      fetch: async (urlOrReq) => {
        const url = typeof urlOrReq === "string" ? urlOrReq : urlOrReq.url;
        if (url.endsWith("/data/embeddings.bin")) {
          return new Response(u16.buffer, { status: 200 });
        }
        if (url.endsWith("/data/embed_index.json")) {
          return new Response(JSON.stringify(indexJson), { status: 200 });
        }
        if (url.endsWith("/data/pages.json")) {
          return new Response(JSON.stringify(pagesArr), { status: 200 });
        }
        return new Response("not found", { status: 404 });
      },
    },
  };
}

function floatToHalf(f) {
  if (f === 0) return 0;
  const sign = f < 0 ? 1 : 0;
  const a = Math.abs(f);
  const e = Math.floor(Math.log2(a));
  const exp = e + 15;
  const frac = Math.round((a / Math.pow(2, e) - 1) * 1024);
  return (sign << 15) | (exp << 10) | (frac & 0x3ff);
}

// Canonical, well-formed Anthropic streaming response. Lives in
// tests/fixtures/anthropic_sse.js alongside its provenance record and the
// "usage fields moved" variant used by the fail-closed test below.
function fakeAnthropicSSEResponse(text) {
  return anthropicSSEResponse(text);
}

function makeChatRequest({ ip = "1.1.1.1", body } = {}) {
  return new Request("https://x/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "CF-Connecting-IP": ip,
    },
    body: JSON.stringify(body || { query: "Tell me about Roswell" }),
  });
}

beforeEach(() => _resetCaches());

describe("handleChat", () => {
  test("happy path: streams SSE response with citations meta event", async () => {
    const kv = makeKV();
    const assets = makeAssetsEnv();
    const captured = [];
    const env = {
      ...assets,
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async (url, init) => {
        captured.push({ url, init });
        return fakeAnthropicSSEResponse("Roswell appears in [card-a:1].");
      },
    };
    const r = await handleChat(makeChatRequest(), env, opts);
    assert.equal(r.status, 200);
    assert.match(r.headers.get("Content-Type"), /text\/event-stream/);
    const text = await r.text();
    // Citations meta must be sent up-front so the client can render the
    // sidebar before the streaming text arrives.
    assert.match(text, /event: citations/);
    assert.match(text, /card-a/);
    // Anthropic delta should be passed through as `event: text` chunks.
    assert.match(text, /event: text/);
    assert.match(text, /Roswell appears/);
    // System prompt should reach Anthropic.
    assert.equal(captured.length, 1);
    const sentBody = JSON.parse(captured[0].init.body);
    assert.match(sentBody.system, /\[card_id:page\]/);
    assert.equal(sentBody.stream, true);
    assert.ok(sentBody.max_tokens <= 1024);
  });

  test("rate-limited 6th request returns 429 with BYOK CTA", async () => {
    const kv = makeKV();
    const assets = makeAssetsEnv();
    const env = {
      ...assets,
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => fakeAnthropicSSEResponse("ok"),
    };
    // Each iteration uses a unique query so the semantic cache (which
    // keys on query+passages) doesn't short-circuit subsequent requests.
    // Cache hits skip the rate-counter increment by design — that's the
    // whole point of the abstention/cache shortcuts being free — but it
    // means same-query repeated calls would never advance the counter.
    for (let i = 0; i < RATE_LIMIT; i += 1) {
      const r = await handleChat(
        makeChatRequest({ body: { query: `unique query ${i}` } }),
        env,
        opts,
      );
      assert.equal(r.status, 200, `request ${i + 1} should succeed`);
      await r.text();
    }
    const blocked = await handleChat(
      makeChatRequest({ body: { query: "blocked query" } }),
      env,
      opts,
    );
    assert.equal(blocked.status, 429);
    const j = await blocked.json();
    assert.match(j.error, /rate limit|too many/i);
    assert.match(j.error, /BYOK|key/i);
  });

  test("budget cap returns 503 + BYOK CTA when exceeded", async () => {
    const kv = makeKV();
    // Pre-spend over the cap.
    await kv.put("spend:" + new Date().toISOString().slice(0, 10), String(DAILY_BUDGET_USD + 1));
    const assets = makeAssetsEnv();
    const env = {
      ...assets,
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => fakeAnthropicSSEResponse("ok"),
    };
    const r = await handleChat(makeChatRequest({ ip: "9.9.9.9" }), env, opts);
    assert.equal(r.status, 503);
    const j = await r.json();
    assert.match(j.error, /high traffic|budget|exceeded/i);
    assert.match(j.error, /BYOK|bring your own/i);
  });

  test("cache hit short-circuits Anthropic call", async () => {
    const kv = makeKV();
    const assets = makeAssetsEnv();
    const env = {
      ...assets,
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    let anthropicCalls = 0;
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => {
        anthropicCalls += 1;
        return fakeAnthropicSSEResponse("Cached answer text [card-a:1].");
      },
    };
    // First call: cold, hits Anthropic.
    const r1 = await handleChat(makeChatRequest({ ip: "5.5.5.5" }), env, opts);
    assert.equal(r1.status, 200);
    await r1.text();
    assert.equal(anthropicCalls, 1);
    // Second identical call: cache hit, no Anthropic call.
    const r2 = await handleChat(makeChatRequest({ ip: "5.5.5.5" }), env, opts);
    assert.equal(r2.status, 200);
    const t2 = await r2.text();
    assert.equal(anthropicCalls, 1, "second call should hit cache");
    assert.match(t2, /Cached answer/);
    // The cache replay must include the citations meta + text + done events.
    assert.match(t2, /event: citations/);
    assert.match(t2, /event: done/);
  });

  test("400 on missing query", async () => {
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: makeKV(),
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const r = await handleChat(makeChatRequest({ body: {} }), env, {});
    assert.equal(r.status, 400);
  });

  test("405 on GET", async () => {
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: makeKV(),
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const r = await handleChat(
      new Request("https://x/api/chat", { method: "GET" }),
      env,
      {},
    );
    assert.equal(r.status, 405);
  });

  test("graceful 200 abstention SSE when retrieval is empty", async () => {
    // Build an env where retrieval will return nothing above threshold.
    const u16 = new Uint16Array([
      floatToHalf(0),
      floatToHalf(1),
      floatToHalf(0),
    ]);
    const indexJson = { model_id: "voyage-3", dim: 3, n: 1, pages: [["x", 1]] };
    const pagesArr = [
      { id: "x-p1", card_id: "x", page: 1, title: "T", text: "irrelevant" },
    ];
    const env = {
      ASSETS: {
        fetch: async (urlOrReq) => {
          const url = typeof urlOrReq === "string" ? urlOrReq : urlOrReq.url;
          if (url.endsWith("/data/embeddings.bin"))
            return new Response(u16.buffer, { status: 200 });
          if (url.endsWith("/data/embed_index.json"))
            return new Response(JSON.stringify(indexJson), { status: 200 });
          if (url.endsWith("/data/pages.json"))
            return new Response(JSON.stringify(pagesArr), { status: 200 });
          return new Response("404", { status: 404 });
        },
      },
      CHAT_KV: makeKV(),
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () => {
        throw new Error("anthropic should not be called when no passages");
      },
    };
    const r = await handleChat(makeChatRequest({ ip: "7.7.7.7" }), env, opts);
    assert.equal(r.status, 200);
    const text = await r.text();
    assert.match(text, /not address|no documents/i);
    assert.match(text, /event: done/);
  });

  test("fail closed: moved usage shape is charged non-zero and the cap engages", async () => {
    const kv = makeKV();
    // Pre-spend to a hair under the cap. A correctly fail-closed charge for
    // one unaccountable call must be enough to push cumulative spend over the
    // ceiling; the buggy $0 charge would leave us under it and never trip.
    const day = new Date().toISOString().slice(0, 10);
    await kv.put("spend:" + day, String(DAILY_BUDGET_USD - 0.001));
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      // Upstream is healthy and streams a full answer, but its usage fields
      // have moved to a location the parser doesn't read.
      anthropicFetch: async () =>
        anthropicSSEMovedUsageResponse("Roswell appears in [card-a:1]."),
    };

    // First call goes through (budget still had a sliver) and completes.
    const r1 = await handleChat(makeChatRequest({ ip: "8.8.8.8" }), env, opts);
    assert.equal(r1.status, 200);
    await r1.text();

    // The unaccountable call was charged a conservative non-zero estimate,
    // NOT $0 — cumulative spend must now exceed the cap.
    const spent = parseFloat(kv._store.get("spend:" + day));
    assert.ok(
      spent > DAILY_BUDGET_USD,
      `expected fail-closed charge to push spend over ${DAILY_BUDGET_USD}, got ${spent}`,
    );

    // ...so the very next request is refused by the daily cap.
    const r2 = await handleChat(makeChatRequest({ ip: "8.8.8.9" }), env, opts);
    assert.equal(r2.status, 503);
  });

  test("daily accounting is observable: spend is logged with running total", async () => {
    const kv = makeKV();
    const env = {
      ...makeAssetsEnv(),
      CHAT_KV: kv,
      VOYAGE_API_KEY: "v",
      ANTHROPIC_API_KEY: "a",
    };
    const opts = {
      embedFn: async () => new Float32Array([1, 0, 0]),
      anthropicFetch: async () =>
        anthropicSSEMovedUsageResponse("Roswell appears in [card-a:1]."),
    };

    const logs = [];
    const origLog = console.log;
    const origWarn = console.warn;
    console.log = (...a) => logs.push(a.join(" "));
    console.warn = (...a) => logs.push(a.join(" "));
    try {
      const r = await handleChat(makeChatRequest({ ip: "8.8.8.10" }), env, opts);
      await r.text();
    } finally {
      console.log = origLog;
      console.warn = origWarn;
    }

    const joined = logs.join("\n");
    // A silent zero must be visible, not inferred: the recorded spend and its
    // running cumulative are logged, and the unparseable usage is flagged.
    assert.match(joined, /spend recorded/i);
    assert.match(joined, /cumulative/i);
    assert.match(joined, /unparseable|fallback|usage_parsed/i);
  });
});
