/**
 * Tests for the CardExplorer runtime card-summary loader.
 *
 * When CardExplorer hydrates without a
 * `cards` prop it fetches `/data/cards-summary.json` to populate the
 * grid. Two things were under-tested before the fix-pass:
 *
 *   1. The browser should honor the Worker's Cache-Control header
 *      (1h fresh + 24h stale-while-revalidate).
 *      `cache: "force-cache"` short-circuits that policy and silently
 *      pins stale payloads across tranches. `cache: "default"` is the
 *      right knob for "use the response's cache headers verbatim."
 *
 *   2. A network failure or non-2xx response must not crash the UI —
 *      the loader resolves to `[]` so the grid degrades gracefully.
 *
 * Run with `node --test src/components/card-summary-loader.test.ts`.
 */

import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  loadCardsSummary,
  CARD_SUMMARY_FETCH_OPTIONS,
} from "./card-summary-loader.ts";

// --- fetch mocking ----------------------------------------------------

interface FetchCall {
  url: string;
  options: RequestInit | undefined;
}

const _origFetch = globalThis.fetch;
let _calls: FetchCall[] = [];

function installFetch(
  handler: (url: string) => { ok: boolean; body: unknown } | Promise<{ ok: boolean; body: unknown }>,
): void {
  _calls = [];
  // @ts-expect-error — test-only override; globalThis.fetch is assignable.
  globalThis.fetch = async (url: string, options?: RequestInit) => {
    _calls.push({ url, options });
    const res = await handler(url);
    return {
      ok: res.ok,
      json: async () => res.body,
    } as unknown as Response;
  };
}

function installRejectingFetch(error: Error): void {
  _calls = [];
  // @ts-expect-error — test-only override.
  globalThis.fetch = async (url: string, options?: RequestInit) => {
    _calls.push({ url, options });
    throw error;
  };
}

beforeEach(() => {
  _calls = [];
});

afterEach(() => {
  globalThis.fetch = _origFetch;
});

// --- fetch options ----------------------------------------------------

test('CARD_SUMMARY_FETCH_OPTIONS uses cache: "default" (honor Worker Cache-Control)', () => {
  // `cache: "default"` lets the browser respect the Worker's
  // 1h-fresh + 24h-SWR policy; `"force-cache"` would
  // silently pin stale payloads across tranches.
  assert.equal(CARD_SUMMARY_FETCH_OPTIONS.cache, "default");
});

// --- happy path -------------------------------------------------------

test("loadCardsSummary resolves to the array when fetch returns 2xx + array body", async () => {
  installFetch(() => ({
    ok: true,
    body: [
      { card_id: "aaaa", title: "Card A" },
      { card_id: "bbbb", title: "Card B" },
    ],
  }));
  const out = await loadCardsSummary("");
  assert.equal(out.length, 2);
  assert.equal(out[0].card_id, "aaaa");
});

test("loadCardsSummary requests the correct URL relative to the base", async () => {
  installFetch(() => ({ ok: true, body: [] }));
  await loadCardsSummary("/preview");
  assert.equal(_calls.length, 1);
  assert.equal(_calls[0].url, "/preview/data/cards-summary.json");
});

test('loadCardsSummary forwards cache: "default" to fetch', async () => {
  installFetch(() => ({ ok: true, body: [] }));
  await loadCardsSummary("");
  assert.equal(_calls.length, 1);
  // The Worker's Cache-Control must drive freshness; force-cache would
  // ignore SWR and pin stale tranches.
  assert.equal(_calls[0].options?.cache, "default");
});

// --- failure modes -----------------------------------------------------

test("loadCardsSummary resolves to [] when fetch rejects (network error)", async () => {
  installRejectingFetch(new Error("network down"));
  const out = await loadCardsSummary("");
  // Must not throw — the UI degrades to an empty grid + the
  // [NO MATCH] block rather than hanging on an exception.
  assert.deepEqual(out, []);
});

test("loadCardsSummary resolves to [] when fetch returns non-2xx", async () => {
  installFetch(() => ({ ok: false, body: null }));
  const out = await loadCardsSummary("");
  assert.deepEqual(out, []);
});

test("loadCardsSummary resolves to [] when JSON body is not an array (defensive)", async () => {
  installFetch(() => ({ ok: true, body: { cards: "wrong-shape" } }));
  const out = await loadCardsSummary("");
  // Forward-compat guard: a schema drift on the JSON side must not
  // crash the client. Drop the payload silently rather than render
  // garbage.
  assert.deepEqual(out, []);
});
