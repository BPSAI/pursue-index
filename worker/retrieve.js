// /api/retrieve — query the corpus by cosine similarity over the
// shipped voyage-3 embeddings.
//
// Architecture:
//   /data/embeddings.bin      — float16 row-major n*dim vectors (8 MB)
//   /data/embed_index.json    — parallel [card_id, page] tuples + meta
//   /data/pages.json          — full per-page text used for snippets
//
// The Worker stays warm long enough that we cache the parsed Float32Array
// across requests in module-level state. Cold start re-fetches via
// env.ASSETS.fetch — which goes against the same Worker static-asset
// pipeline, no extra origin round-trip. Voyage embedding for the query
// is server-side both for anonymous and BYOK tiers.
//
// The cosine math is exposed as pure functions so they can be tested
// without mocking ASSETS or fetch.

import {
  buildSlugIndex,
  extractLiteralCardIds,
  extractLiteralSlugs,
  literalIdPassages,
  literalSlugPassages,
  mergeLiteralAndSemantic,
} from "./retrieve_literal_id.js";
import { buildPassage } from "./retrieve_passage.js";

// Re-export from the extracted helper module so callers (tests,
// adjacent worker modules) can keep importing from `retrieve.js` —
// the central module surface — without knowing whether the helper
// was inlined or extracted. Lets us reorganize internals without
// breaking import paths in test fixtures or future call sites.
export {
  extractLiteralCardIds,
  extractLiteralSlugs,
} from "./retrieve_literal_id.js";

const VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings";
const VOYAGE_MODEL = "voyage-3";
const DEFAULT_K = 8;
// Cosine-similarity floor for retrieval. Voyage-3 paraphrased queries land
// in the 0.3–0.5 range against the corpus even when semantically relevant
// (observed: "Did Apollo 17 astronauts report any anomalies?" misses the
// Apollo 17 page at 0.5 because the page text uses different vocabulary).
// 0.30 lets borderline-but-plausible matches through; the model's Rule 3
// abstention discipline catches the actually-irrelevant cases via the
// system prompt rather than via this threshold.
const SCORE_THRESHOLD = 0.3;
const SNIPPET_CHARS = 600; // generous — used as prompt context, not display.

/**
 * Normalize a vector to unit length, in-place safe.
 * Returns a new Float32Array; leaves the input untouched. Zero vectors
 * are returned as-is (no division by zero).
 */
export function normalizeVector(v) {
  let sum = 0;
  for (let i = 0; i < v.length; i += 1) sum += v[i] * v[i];
  if (sum === 0) return new Float32Array(v);
  const inv = 1 / Math.sqrt(sum);
  const out = new Float32Array(v.length);
  for (let i = 0; i < v.length; i += 1) out[i] = v[i] * inv;
  return out;
}

/**
 * Top-k cosine similarity over a flat Float32Array corpus of shape
 * (n*dim) row-major. Returns sorted [{index, score}] descending.
 *
 * Both `query` and `corpus` may or may not be pre-normalized; we don't
 * assume. The corpus is normalized lazily by the caller (we ship
 * unit-norm voyage-3 vectors so this is essentially a dot product).
 */
export function cosineTopK(query, corpus, k, n) {
  const dim = query.length;
  // Normalize the query once.
  const q = normalizeVector(query);
  // Use a partial sort: collect all (index, score) then sort. n=4119 is
  // small enough that a heap is over-engineered.
  const scores = new Array(n);
  for (let i = 0; i < n; i += 1) {
    let dot = 0;
    let mag = 0;
    const base = i * dim;
    for (let j = 0; j < dim; j += 1) {
      const v = corpus[base + j];
      dot += q[j] * v;
      mag += v * v;
    }
    const denom = mag === 0 ? 1 : Math.sqrt(mag);
    scores[i] = { index: i, score: dot / denom };
  }
  scores.sort((a, b) => b.score - a.score);
  return scores.slice(0, Math.min(k, n));
}

/** Decode a Float16 buffer to Float32. Voyage embeddings ship as float16. */
export function float16ToFloat32(buf) {
  // Manual half-precision decoder. Avoids depending on a library when
  // the algorithm is 20 lines of bit-twiddling.
  const u16 = new Uint16Array(buf);
  const out = new Float32Array(u16.length);
  for (let i = 0; i < u16.length; i += 1) {
    out[i] = halfToFloat(u16[i]);
  }
  return out;
}

function halfToFloat(h) {
  const sign = (h & 0x8000) >> 15;
  const exp = (h & 0x7c00) >> 10;
  const frac = h & 0x03ff;
  if (exp === 0) {
    if (frac === 0) return sign ? -0 : 0;
    // subnormal
    return (sign ? -1 : 1) * (frac / 1024) * Math.pow(2, -14);
  }
  if (exp === 0x1f) {
    return frac === 0 ? (sign ? -Infinity : Infinity) : NaN;
  }
  return (sign ? -1 : 1) * (1 + frac / 1024) * Math.pow(2, exp - 15);
}

// ---------------------------------------------------------------------------
// Module-level cache (warm-Worker reuse).
// ---------------------------------------------------------------------------

let _corpusCache = null; // { vectors: Float32Array, n: number, dim: number }
let _indexCache = null; // { pages: [[card_id, page], ...], dim, n }
let _pagesCache = null; // Map<`${card_id}-p${page}`, PageRecord>
let _slugCache = null; // Map<canonicalSlug, card_id>

/** Reset caches — for tests only. */
export function _resetCaches() {
  _corpusCache = null;
  _indexCache = null;
  _pagesCache = null;
  _slugCache = null;
}

async function loadCorpus(env) {
  if (_corpusCache) return _corpusCache;
  const res = await env.ASSETS.fetch("https://assets/data/embeddings.bin");
  if (!res.ok) throw new Error(`embeddings.bin fetch failed: ${res.status}`);
  const buf = await res.arrayBuffer();
  const vectors = float16ToFloat32(buf);
  // We don't know n/dim from the buffer alone; the index will fix that.
  _corpusCache = { vectors, n: 0, dim: 0 };
  return _corpusCache;
}

async function loadIndex(env) {
  if (_indexCache) return _indexCache;
  const res = await env.ASSETS.fetch("https://assets/data/embed_index.json");
  if (!res.ok) throw new Error(`embed_index.json fetch failed: ${res.status}`);
  const meta = await res.json();
  _indexCache = { pages: meta.pages, dim: meta.dim, n: meta.n };
  return _indexCache;
}

async function loadPages(env) {
  if (_pagesCache) return _pagesCache;
  const res = await env.ASSETS.fetch("https://assets/data/pages.json");
  if (!res.ok) throw new Error(`pages.json fetch failed: ${res.status}`);
  const arr = await res.json();
  const map = new Map();
  for (const p of arr) {
    map.set(`${p.card_id}-p${p.page}`, p);
  }
  _pagesCache = map;
  return _pagesCache;
}

// ---------------------------------------------------------------------------
// Voyage query embedding.
// ---------------------------------------------------------------------------

/**
 * Embed a single query string via Voyage. `voyageFetch` is injected to keep
 * the function testable; in production it's the global `fetch`.
 */
export async function embedQuery(query, apiKey, voyageFetch = fetch) {
  if (!apiKey) throw new Error("VOYAGE_API_KEY missing");
  const res = await voyageFetch(VOYAGE_EMBED_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      input: [query],
      model: VOYAGE_MODEL,
      input_type: "query",
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`voyage embed failed ${res.status}: ${body}`);
  }
  const data = await res.json();
  const vec = data?.data?.[0]?.embedding;
  if (!Array.isArray(vec)) {
    throw new Error("voyage response missing data[0].embedding");
  }
  return new Float32Array(vec);
}

// ---------------------------------------------------------------------------
// Snippet extraction.
// ---------------------------------------------------------------------------

/**
 * Pick a snippet from `text` centered on the first match of any term
 * in `query`. Falls back to the first SNIPPET_CHARS chars if no match.
 */
export function makeSnippet(text, query, maxChars = SNIPPET_CHARS) {
  if (!text) return "";
  const trimmed = text.trim();
  if (trimmed.length <= maxChars) return trimmed;
  const terms = (query || "")
    .toLowerCase()
    .split(/\W+/)
    .filter((t) => t.length > 2);
  let pos = -1;
  const lower = trimmed.toLowerCase();
  for (const t of terms) {
    const i = lower.indexOf(t);
    if (i !== -1 && (pos === -1 || i < pos)) pos = i;
  }
  if (pos === -1) return trimmed.slice(0, maxChars).trim() + "…";
  const half = Math.floor(maxChars / 2);
  const start = Math.max(0, pos - half);
  const end = Math.min(trimmed.length, start + maxChars);
  let snip = trimmed.slice(start, end);
  if (start > 0) snip = "…" + snip;
  if (end < trimmed.length) snip = snip + "…";
  return snip;
}

// ---------------------------------------------------------------------------
// Public retrieval entrypoint.
// ---------------------------------------------------------------------------

/**
 * Retrieve top-k passages for a query.
 *
 * Returns an array of {card_id, page, title, snippet, score, page_text}
 * sorted with literal-ID hits first (in query mention order), then
 * dense-embedding hits descending by cosine score, filtered by
 * SCORE_THRESHOLD. The output is capped at `k` entries total.
 *
 * `env` must provide ASSETS and VOYAGE_API_KEY. `embedFn` overrides the
 * embedding step in tests.
 */
export async function retrievePassages(query, k, env, embedFn) {
  const useEmbed = embedFn || ((q) => embedQuery(q, env.VOYAGE_API_KEY));
  const [corpus, index, pages, queryVec] = await Promise.all([
    loadCorpus(env),
    loadIndex(env),
    loadPages(env),
    useEmbed(query),
  ]);
  // Patch corpus dims now that we know them.
  corpus.dim = index.dim;
  corpus.n = index.n;
  if (queryVec.length !== index.dim) {
    throw new Error(
      `query vector dim ${queryVec.length} != index dim ${index.dim}`,
    );
  }
  const hits = cosineTopK(queryVec, corpus.vectors, k, index.n).filter(
    (h) => h.score >= SCORE_THRESHOLD,
  );
  // `buildPassage` returns null for a hit whose pages.json record is
  // missing or textless — a citation built from one would be blank.
  const semanticPassages = hits
    .map((h) => {
      const [card_id, page] = index.pages[h.index];
      return buildPassage({
        card_id,
        page,
        pageRec: pages.get(`${card_id}-p${page}`),
        query,
        score: h.score,
        makeSnippetFn: makeSnippet,
      });
    })
    .filter((p) => p !== null);

  // Sprint 4b Theme A: literal-ID bypass. Detect hex card_ids in the
  // query, prepend exact-match chunks, dedup by `card_id+page`, cap at k.
  // Sprint 4 follow-up (Option C, 2026-06-02): also detect
  // agency-prefixed slugs like DOW-UAP-D017. Both literal lanes feed
  // the same prepend-then-merge pipeline so a query mentioning a hex
  // id AND a slug surfaces both in mention order.
  const ids = extractLiteralCardIds(query);
  const slugs = extractLiteralSlugs(query);
  if (ids.length === 0 && slugs.length === 0) return semanticPassages;
  const hexHits = literalIdPassages(
    ids,
    index.pages,
    pages,
    query,
    makeSnippet,
  );
  let slugHits = [];
  if (slugs.length > 0) {
    // Lazy-build the slug index from the pages cache; ~O(pages × titleLen).
    if (!_slugCache) _slugCache = buildSlugIndex(pages);
    slugHits = literalSlugPassages(
      slugs,
      _slugCache,
      index.pages,
      pages,
      query,
      makeSnippet,
    );
  }
  // Mention order in the query is preserved by interleaving the hex
  // and slug hits in the order the regexes found them. The simpler
  // policy here (hex hits first, then slug hits) matches the mention
  // order in all queries where each pattern appears at most once —
  // the common case — and remains stable when both patterns appear
  // mixed (downstream `mergeLiteralAndSemantic` dedup is order-preserving).
  return mergeLiteralAndSemantic(
    [...hexHits, ...slugHits],
    semanticPassages,
    k,
  );
}

// ---------------------------------------------------------------------------
// HTTP handler.
// ---------------------------------------------------------------------------

/**
 * Handle POST /api/retrieve. Body: {query: string, k?: number}.
 * Returns {passages: [...], usage: {model, ...}}.
 */
export async function handleRetrieve(request, env) {
  if (request.method !== "POST") {
    return jsonResponse({ error: "method not allowed" }, 405);
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: "invalid JSON body" }, 400);
  }
  const query = (body?.query || "").toString().trim();
  if (!query) return jsonResponse({ error: "query required" }, 400);
  if (query.length > 1000) {
    return jsonResponse({ error: "query too long (max 1000 chars)" }, 400);
  }
  const k = Math.max(1, Math.min(20, Number(body?.k) || DEFAULT_K));
  try {
    const passages = await retrievePassages(query, k, env);
    return jsonResponse({
      passages,
      model: VOYAGE_MODEL,
      k,
      threshold: SCORE_THRESHOLD,
    });
  } catch (err) {
    console.error("retrieve error", err);
    return jsonResponse({ error: String(err.message || err) }, 502);
  }
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
