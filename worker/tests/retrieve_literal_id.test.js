// Tests for the literal-ID bypass in retrieval.
//
// Sprint 4b Theme A (per Sprint 6.0 finding): dense voyage-3 embeddings
// reliably miss the literal-ID-lookup intent ("what's in card
// 13f86e95aed52840?"). The semantic neighborhood of a hex string is
// pretty much the entire corpus. Detect explicit 16-hex card IDs in
// the user query and PREPEND exact-match card chunks before the
// semantic top-k results — dedup by `card_id+page`, cap at k.
//
// Detection patterns:
//   * 16-hex card_id   (`/\b[a-f0-9]{16}\b/g` case-insensitive)
//
// (We deliberately do NOT detect ad-hoc patterns like `D##` or
// `pursue-NNN` — those don't exist in this project; the index is
// canonically 16-hex.)

import { describe, test, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { retrievePassages, _resetCaches } from "../retrieve.js";
import { extractLiteralCardIds } from "../retrieve.js";

// Same float16 packing helpers as retrieve_handler.test.js. Copied
// (rather than imported) so this test file stays self-contained — it
// gets executed standalone by `npm run test`.
function floatsToFloat16Buffer(rows) {
  const dim = rows[0].length;
  const u16 = new Uint16Array(rows.length * dim);
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = 0; j < dim; j += 1) {
      u16[i * dim + j] = floatToHalf(rows[i][j]);
    }
  }
  return u16.buffer;
}

function floatToHalf(f) {
  if (f === 0) return 0;
  const sign = f < 0 ? 1 : 0;
  const a = Math.abs(f);
  const e = Math.floor(Math.log2(a));
  const exp = e + 15;
  const frac = Math.round((a / Math.pow(2, e) - 1) * 1024);
  if (exp <= 0 || exp >= 31) throw new Error("float16 overflow in fixture");
  return (sign << 15) | (exp << 10) | (frac & 0x3ff);
}

function makeMockEnv(rows, indexPages, pagesArr, voyageVec) {
  const corpusBuf = floatsToFloat16Buffer(rows);
  const indexJson = {
    model_id: "voyage-3",
    dim: rows[0].length,
    n: rows.length,
    pages: indexPages,
  };
  const ASSETS = {
    fetch: async (urlOrReq) => {
      const url = typeof urlOrReq === "string" ? urlOrReq : urlOrReq.url;
      if (url.endsWith("/data/embeddings.bin")) {
        return new Response(corpusBuf, { status: 200 });
      }
      if (url.endsWith("/data/embed_index.json")) {
        return new Response(JSON.stringify(indexJson), { status: 200 });
      }
      if (url.endsWith("/data/pages.json")) {
        return new Response(JSON.stringify(pagesArr), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    },
  };
  return {
    env: { ASSETS, VOYAGE_API_KEY: "test" },
    embedFn: async () => new Float32Array(voyageVec),
  };
}

beforeEach(() => _resetCaches());

describe("extractLiteralCardIds", () => {
  test("returns the empty list when the query has no hex tokens", () => {
    assert.deepEqual(extractLiteralCardIds("what's in roswell?"), []);
  });

  test("extracts a single 16-hex card_id", () => {
    const ids = extractLiteralCardIds(
      "what's in card 13f86e95aed52840?",
    );
    assert.deepEqual(ids, ["13f86e95aed52840"]);
  });

  test("extracts multiple 16-hex card_ids preserving order, deduped", () => {
    const ids = extractLiteralCardIds(
      "compare 13f86e95aed52840 to 0b298cfc9c65a4d6 and 13f86e95aed52840",
    );
    assert.deepEqual(ids, ["13f86e95aed52840", "0b298cfc9c65a4d6"]);
  });

  test("is case-insensitive but normalizes to lowercase", () => {
    const ids = extractLiteralCardIds("see 13F86E95AED52840 please");
    assert.deepEqual(ids, ["13f86e95aed52840"]);
  });

  test("ignores 15-hex and 17-hex tokens (false-positive guard)", () => {
    // 15 chars and 17 chars must not match; word-boundary anchors.
    assert.deepEqual(
      extractLiteralCardIds("nope 13f86e95aed5284 short 13f86e95aed528401 long"),
      [],
    );
  });

  test("matches a hex token sitting at the start/end of the string", () => {
    assert.deepEqual(
      extractLiteralCardIds("13f86e95aed52840 is the card"),
      ["13f86e95aed52840"],
    );
    assert.deepEqual(
      extractLiteralCardIds("the card is 13f86e95aed52840"),
      ["13f86e95aed52840"],
    );
  });

  test("matches 16-digit pure-numeric strings (regex doesn't exclude 0-9-only)", () => {
    // nayru P1#3: ``/\b[a-f0-9]{16}\b/g`` accepts pure-digit
    // 16-char strings because hex digits include 0-9. A 16-digit
    // phone number / case number in a user query technically
    // matches. ``literalIdPassages`` silently drops unknown IDs
    // (the corpus is keyed by real card_ids), so the false
    // positive is benign: it triggers a no-op lookup, falls
    // through to semantic search. Lock the behavior with a test so
    // any future "tighten to require at least one a-f" change is
    // an explicit decision, not an accident.
    assert.deepEqual(
      extractLiteralCardIds("call 5551234567890123 about it"),
      ["5551234567890123"],
    );
  });
});

describe("retrievePassages — literal-ID bypass", () => {
  // Three corpus rows; query embedding is most similar to row 1 (b).
  // Card "a" sits at row 0 and SHOULD NOT win semantically.
  const rows = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ];
  // Use real 16-hex card_id fixtures so the LITERAL_CARD_ID_RE matches.
  const ID_A = "aaaaaaaaaaaaaaaa";
  const ID_B = "bbbbbbbbbbbbbbbb";
  const ID_C = "cccccccccccccccc";
  const indexPages = [
    [ID_A, 1],
    [ID_B, 1],
    [ID_C, 1],
  ];
  const pagesArr = [
    { id: `${ID_A}-p1`, card_id: ID_A, page: 1, title: "A", text: "Apollo report" },
    { id: `${ID_B}-p1`, card_id: ID_B, page: 1, title: "B", text: "Roswell file" },
    { id: `${ID_C}-p1`, card_id: ID_C, page: 1, title: "C", text: "Other" },
  ];

  test("no literal-ID in query → result order unchanged from semantic top-k", async () => {
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    const out = await retrievePassages("Roswell", 8, env, embedFn);
    // Row 1 (card-b) is the semantic winner; no ID in query so nothing
    // is prepended.
    assert.equal(out.length, 1, "score threshold filters to one hit");
    assert.equal(out[0].card_id, "bbbbbbbbbbbbbbbb");
  });

  test("literal-ID in query → exact-match card prepended to semantic results", async () => {
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    // Mention card-a's id but ask a question about Roswell — semantic
    // winner is still card-b, but card-a should appear first because
    // it was literally addressed.
    const out = await retrievePassages(
      "what's in aaaaaaaaaaaaaaaa about Roswell?",
      8,
      env,
      embedFn,
    );
    assert.ok(out.length >= 2, `expected ≥2 hits, got ${out.length}`);
    assert.equal(out[0].card_id, "aaaaaaaaaaaaaaaa", "literal-ID hit leads");
    assert.equal(out[1].card_id, "bbbbbbbbbbbbbbbb", "semantic hit follows");
  });

  test("16-digit numeric token in query → no crash, semantic-only results", async () => {
    // nayru P1#3 end-to-end guard: ``5551234567890123`` is a valid
    // ``/\b[a-f0-9]{16}\b/`` match (all hex digits 0-9). The
    // literal-ID lane should silently drop it (no card with that
    // ID), and the request must complete successfully via the
    // semantic-search fallback. This is the "16-digit phone or
    // case number in the chat input" case.
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    const out = await retrievePassages(
      "what does case 5551234567890123 say about Roswell?",
      8,
      env,
      embedFn,
    );
    assert.equal(out.length, 1, "semantic lane returns one hit");
    assert.equal(out[0].card_id, "bbbbbbbbbbbbbbbb", "Roswell hit unchanged");
  });

  test("literal-ID present but not in the corpus → behavior unchanged", async () => {
    const { env, embedFn } = makeMockEnv(rows, indexPages, pagesArr, [0, 1, 0]);
    // A well-formed but unknown 16-hex token. The bypass code should
    // silently no-op for unknown IDs (don't fail; just fall back to
    // semantic).
    const out = await retrievePassages(
      "what's in card deadbeefdeadbeef about Roswell?",
      8,
      env,
      embedFn,
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].card_id, "bbbbbbbbbbbbbbbb");
  });

  test("literal-ID hit dedupes when semantic results contain the same card+page", async () => {
    // Build a fixture where the literal-ID card ALSO wins semantically.
    // The result must not list the same (card_id, page) twice.
    const sameRows = [[1, 0, 0]];
    const sameIndexPages = [["aaaaaaaaaaaaaaaa", 1]];
    const samePages = [
      { id: "aaaaaaaaaaaaaaaa-p1", card_id: "aaaaaaaaaaaaaaaa", page: 1, title: "A", text: "Apollo report" },
    ];
    const { env, embedFn } = makeMockEnv(sameRows, sameIndexPages, samePages, [1, 0, 0]);
    const out = await retrievePassages(
      "aaaaaaaaaaaaaaaa Apollo",
      8,
      env,
      embedFn,
    );
    // One row total — the literal-ID prepend matched the same chunk
    // the semantic search would have returned; the dedup must collapse
    // them so the array contains one entry, not two.
    assert.equal(out.length, 1, "dedup by card_id+page");
    assert.equal(out[0].card_id, "aaaaaaaaaaaaaaaa");
  });

  test("k cap is respected after the literal-ID prepend", async () => {
    // Three corpus rows, all weakly aligned with the query. Mention
    // two literal IDs. Ask for k=2 — output should be at most 2 entries.
    const lowRows = [
      [0.9, 0.1, 0],
      [0.85, 0.05, 0.1],
      [0.8, 0.05, 0.15],
    ];
    const lowPages = [
      ["aaaaaaaaaaaaaaaa", 1],
      ["bbbbbbbbbbbbbbbb", 1],
      ["cccccccccccccccc", 1],
    ];
    const lowPagesArr = [
      { card_id: "aaaaaaaaaaaaaaaa", page: 1, title: "A", text: "x" },
      { card_id: "bbbbbbbbbbbbbbbb", page: 1, title: "B", text: "y" },
      { card_id: "cccccccccccccccc", page: 1, title: "C", text: "z" },
    ];
    const { env, embedFn } = makeMockEnv(lowRows, lowPages, lowPagesArr, [1, 0, 0]);
    const out = await retrievePassages(
      "discuss aaaaaaaaaaaaaaaa and bbbbbbbbbbbbbbbb",
      2,
      env,
      embedFn,
    );
    assert.equal(out.length, 2, "result capped at k=2");
    // Literal-ID hits lead in mention order; the third card is dropped
    // by the cap even though it would have qualified semantically.
    assert.equal(out[0].card_id, "aaaaaaaaaaaaaaaa");
    assert.equal(out[1].card_id, "bbbbbbbbbbbbbbbb");
  });
});
