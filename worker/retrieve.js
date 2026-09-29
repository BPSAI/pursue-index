// /api/retrieve — query the corpus by cosine similarity over the
// shipped voyage-3 embeddings.
//
// Architecture:
//   /data/embeddings.bin      — float16 row-major n*dim vectors
//   /data/embed_index.json    — parallel [card_id, page] tuples + meta
//   /data/retrieve/           — per-row card_id/page/title/text, sharded in
//                               index row order (retrieve_rows.js)
//
// Workers isolates have 128 MB. The vectors stay float16 in memory (a
// Uint16Array, ~30 MB at 14,480 x 1,024) and are scored through a lookup
// table (retrieve_vectors.js); citations read only the text shards holding
// a query's hits, never the whole pages.json. The index and vectors load
// once per isolate — concurrent cold requests share one load — and stay
// cached while the Worker is warm. Loads go through env.ASSETS.fetch, the
// Worker static-asset pipeline, with no extra origin round-trip. Voyage
// embedding for the query is server-side both for anonymous and BYOK
// tiers.

import {
  buildSlugIndex,
  extractLiteralCardIds,
  extractLiteralSlugs,
  literalIdPassages,
  literalSlugPassages,
  mergeLiteralAndSemantic,
} from "./retrieve_literal_id.js";
import { buildPassage } from "./retrieve_passage.js";
import { loadRows, loadRowsManifest, loadTitles } from "./retrieve_rows.js";
import { cosineTopKF16, float16Lut, loadFloat16Asset, rowNorms } from "./retrieve_vectors.js";
import { loadAssetBytes } from "../web/src/lib/chunked-asset.js";

// Re-export from the extracted helper modules so callers (tests,
// adjacent worker modules) can keep importing from `retrieve.js` —
// the central module surface — without knowing whether the helper
// was inlined or extracted. Lets us reorganize internals without
// breaking import paths in test fixtures or future call sites.
export {
  extractLiteralCardIds,
  extractLiteralSlugs,
} from "./retrieve_literal_id.js";
export { cosineTopK, normalizeVector } from "./retrieve_math.js";
export { float16ToFloat32 } from "./retrieve_vectors.js";

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

// ---------------------------------------------------------------------------
// Module-level cache (warm-Worker reuse).
// ---------------------------------------------------------------------------

// Each entry is the load's promise, so concurrent cold requests share one
// load instead of each allocating their own copy. A rejected load is
// dropped so the next request retries it.
const _cache = new Map();

function once(key, load) {
  let p = _cache.get(key);
  if (!p) {
    p = load();
    _cache.set(key, p);
    p.catch(() => {
      if (_cache.get(key) === p) _cache.delete(key);
    });
  }
  return p;
}

/** Reset caches — for tests only. */
export function _resetCaches() {
  _cache.clear();
}

const assetsFetch = (env) => (u) => env.ASSETS.fetch(u);

function loadIndex(env) {
  return once("index", async () => {
    const bytes = await loadAssetBytes("https://assets/data/embed_index.json", assetsFetch(env));
    if (bytes === null) throw new Error("embed_index.json fetch failed: 404");
    const meta = JSON.parse(new TextDecoder().decode(bytes));
    return { pages: meta.pages, dim: meta.dim, n: meta.n };
  });
}

// Vectors are streamed part by part into one Uint16Array sized from the
// index; row norms are computed once so scoring is a dot product per row.
function loadCorpus(env) {
  return once("corpus", async () => {
    const index = await loadIndex(env);
    const vectors = await loadFloat16Asset(
      "https://assets/data/embeddings.bin",
      assetsFetch(env),
      index.n * index.dim,
    );
    if (vectors === null) throw new Error("embeddings.bin fetch failed: 404");
    const lut = float16Lut();
    const norms = rowNorms(vectors, index.n, index.dim, lut);
    return { index, vectors, norms, lut };
  });
}

function loadManifest(env) {
  return once("rows", () => loadRowsManifest(assetsFetch(env)));
}

function loadSlugIndex(env) {
  return once("slugs", async () =>
    buildSlugIndex(await loadTitles(assetsFetch(env), await loadManifest(env))),
  );
}

/** First index row of `cardId`, or -1. */
function firstRow(indexPages, cardId) {
  for (let i = 0; i < indexPages.length; i += 1) {
    if (indexPages[i][0] === cardId) return i;
  }
  return -1;
}

/**
 * Page records for `rowIds`, keyed `${card_id}-p${page}` as the citation
 * builders look them up. A shard row that does not describe its index row
 * (the payloads drifted apart) is left out, so `buildPassage` skips the
 * hit, logged, rather than citing the wrong page.
 */
async function pageRecords(env, indexPages, rowIds) {
  const rows = await loadRows(assetsFetch(env), await loadManifest(env), rowIds);
  const out = new Map();
  for (const [i, rec] of rows) {
    const [card_id, page] = indexPages[i];
    if (rec.card_id === card_id && rec.page === page) out.set(`${card_id}-p${page}`, rec);
  }
  return out;
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
  // Only the Voyage call overlaps the corpus load.
  const [corpus, queryVec] = await Promise.all([loadCorpus(env), useEmbed(query)]);
  const { index } = corpus;
  if (queryVec.length !== index.dim) {
    throw new Error(
      `query vector dim ${queryVec.length} != index dim ${index.dim}`,
    );
  }
  const hits = cosineTopKF16(queryVec, corpus.vectors, corpus.norms, corpus.lut, k, index.n).filter(
    (h) => h.score >= SCORE_THRESHOLD,
  );

  // Sprint 4b Theme A: literal-ID bypass. Detect hex card_ids in the
  // query, prepend exact-match chunks, dedup by `card_id+page`, cap at k.
  // Sprint 4 follow-up (Option C, 2026-06-02): also detect
  // agency-prefixed slugs like DOW-UAP-D017. Both literal lanes feed
  // the same prepend-then-merge pipeline so a query mentioning a hex
  // id AND a slug surfaces both in mention order.
  const ids = extractLiteralCardIds(query);
  const slugs = extractLiteralSlugs(query);
  // The slug index is built from the small per-card titles file.
  const slugIndex = slugs.length > 0 ? await loadSlugIndex(env) : null;
  const literalCards = [...ids, ...slugs.map((s) => slugIndex.get(s)).filter(Boolean)];

  // Fetch the text of every row any lane may cite, and nothing else.
  const rowIds = [
    ...hits.map((h) => h.index),
    ...literalCards.map((c) => firstRow(index.pages, c)).filter((i) => i >= 0),
  ];
  const pages = await pageRecords(env, index.pages, rowIds);

  // `buildPassage` returns null for a hit whose page record is missing
  // or textless — a citation built from one would be blank.
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

  if (ids.length === 0 && slugs.length === 0) return semanticPassages;
  const hexHits = literalIdPassages(
    ids,
    index.pages,
    pages,
    query,
    makeSnippet,
  );
  const slugHits = slugs.length > 0
    ? literalSlugPassages(slugs, slugIndex, index.pages, pages, query, makeSnippet)
    : [];
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
