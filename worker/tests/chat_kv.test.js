// Tests for the per-IP rate limit, semantic cache, and global $ budget
// against a tiny in-memory KV mock.

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  checkAndIncrementRate,
  cacheKey,
  readCache,
  writeCache,
  checkBudget,
  recordSpend,
  RATE_LIMIT,
  DAILY_BUDGET_USD,
} from "../chat_kv.js";

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

let kv;
beforeEach(() => {
  kv = makeKV();
});

describe("checkAndIncrementRate", () => {
  test("allows the first N requests then refuses", async () => {
    const ip = "1.2.3.4";
    for (let i = 0; i < RATE_LIMIT; i += 1) {
      const ok = await checkAndIncrementRate(kv, ip);
      assert.equal(ok.allowed, true, `request ${i + 1} should be allowed`);
      assert.equal(ok.count, i + 1);
    }
    const blocked = await checkAndIncrementRate(kv, ip);
    assert.equal(blocked.allowed, false);
    assert.equal(blocked.count, RATE_LIMIT);
  });

  test("isolates counters per IP", async () => {
    for (let i = 0; i < RATE_LIMIT; i += 1) {
      await checkAndIncrementRate(kv, "1.1.1.1");
    }
    const r = await checkAndIncrementRate(kv, "2.2.2.2");
    assert.equal(r.allowed, true);
    assert.equal(r.count, 1);
  });

  test("uses date-bucketed keys (next day resets)", async () => {
    const ip = "9.9.9.9";
    // Fill the bucket on day 1.
    for (let i = 0; i < RATE_LIMIT; i += 1) {
      await checkAndIncrementRate(kv, ip, "2026-05-01");
    }
    const blocked = await checkAndIncrementRate(kv, ip, "2026-05-01");
    assert.equal(blocked.allowed, false);
    // New day → new bucket → fresh counter.
    const fresh = await checkAndIncrementRate(kv, ip, "2026-05-02");
    assert.equal(fresh.allowed, true);
    assert.equal(fresh.count, 1);
  });
});

describe("cacheKey + readCache + writeCache", () => {
  test("identical query+passages produces stable cache key", () => {
    const passages = [
      { card_id: "a", page: 1 },
      { card_id: "b", page: 2 },
    ];
    const k1 = cacheKey("Roswell?", passages);
    const k2 = cacheKey("Roswell?", passages);
    assert.equal(k1, k2);
  });

  test("different passages → different keys", () => {
    const k1 = cacheKey("q", [{ card_id: "a", page: 1 }]);
    const k2 = cacheKey("q", [{ card_id: "b", page: 1 }]);
    assert.notEqual(k1, k2);
  });

  test("different query → different keys (case + whitespace normalised)", () => {
    const passages = [{ card_id: "a", page: 1 }];
    const k1 = cacheKey("Roswell?", passages);
    const k2 = cacheKey("  ROSWELL?  ", passages);
    assert.equal(k1, k2);
    const k3 = cacheKey("Apollo?", passages);
    assert.notEqual(k1, k3);
  });

  test("readCache returns null on miss, value on hit", async () => {
    const k = cacheKey("q", [{ card_id: "a", page: 1 }]);
    assert.equal(await readCache(kv, k), null);
    await writeCache(kv, k, { answer: "foo", citations: [] });
    const hit = await readCache(kv, k);
    assert.deepEqual(hit, { answer: "foo", citations: [] });
  });
});

describe("checkBudget + recordSpend", () => {
  test("allowed when total under cap", async () => {
    const r = await checkBudget(kv, "2026-05-09");
    assert.equal(r.allowed, true);
    assert.equal(r.spent, 0);
  });

  test("blocks once cumulative spend exceeds DAILY_BUDGET_USD", async () => {
    const day = "2026-05-09";
    await recordSpend(kv, day, DAILY_BUDGET_USD - 0.01);
    let r = await checkBudget(kv, day);
    assert.equal(r.allowed, true);
    await recordSpend(kv, day, 0.05);
    r = await checkBudget(kv, day);
    assert.equal(r.allowed, false);
    assert.ok(r.spent > DAILY_BUDGET_USD);
  });

  test("budget bucket isolates by day", async () => {
    await recordSpend(kv, "2026-05-09", DAILY_BUDGET_USD * 2);
    const r = await checkBudget(kv, "2026-05-10");
    assert.equal(r.allowed, true);
  });

  test("recordSpend returns the running cumulative so accounting is observable", async () => {
    const day = "2026-05-11";
    const a = await recordSpend(kv, day, 1.5);
    assert.equal(a.spent, 1.5);
    const b = await recordSpend(kv, day, 2.25);
    assert.equal(b.spent, 3.75);
  });
});
