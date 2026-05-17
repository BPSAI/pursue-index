// Literal-ID bypass helpers for worker/retrieve.js.
//
// Sprint 4b Theme A (per Sprint 6.0 finding): dense voyage-3 embeddings
// reliably miss the literal-ID-lookup intent ("what's in card
// 13f86e95aed52840?"). The semantic neighborhood of a hex string is
// pretty much the entire corpus. Detect explicit 16-hex card_ids in
// the user query and PREPEND exact-match card chunks before the
// semantic top-k, deduping by `card_id+page` and capping at k.
//
// Pure-function module — no I/O, no caches. Extracted from
// `retrieve.js` to keep that file under the 400-line maintainability
// threshold even though the worker tree isn't Python-arch-checked.

// 16-hex card_id pattern with word-boundary anchors. `\b` treats
// `0-9a-f_` as word chars, which correctly rejects 15/17-hex strings
// (the boundary fails on one side for those lengths) and embedded
// substrings (`13f86e95aed52840_foo` fails because the right-side
// underscore is a word char and breaks the boundary). Case-insensitive
// match; output is normalized to lowercase to match the on-disk
// card_id casing in embed_index.json.
export const LITERAL_CARD_ID_RE = /\b[a-f0-9]{16}\b/gi;

/**
 * Extract 16-hex card_ids from a free-form user query.
 *
 * Returns an order-preserving, deduped, lowercased list.
 *
 * Used by `retrievePassages` to prepend exact-match chunks before
 * semantic top-k, bypassing the voyage-3 dense-embedding miss on
 * hex-string lookups.
 */
export function extractLiteralCardIds(query) {
  if (typeof query !== "string" || !query) return [];
  const seen = new Set();
  const out = [];
  for (const match of query.matchAll(LITERAL_CARD_ID_RE)) {
    const id = match[0].toLowerCase();
    if (!seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

/**
 * Build the literal-ID prepend list. For each card_id in `ids`, find
 * the first chunk in `indexPages` whose card_id matches and emit a
 * passage record. Unknown IDs (not in the corpus index) are silently
 * skipped — better to fall through to semantic search than to fail
 * the request on an unparseable hex string the user happened to type.
 *
 * `makeSnippetFn` is injected (rather than imported from retrieve.js)
 * to avoid a circular dependency.
 */
export function literalIdPassages(ids, indexPages, pagesMap, query, makeSnippetFn) {
  const out = [];
  for (const id of ids) {
    // Linear scan; the corpus is small (~4,127 rows) and this only
    // fires when the query contains a hex token, so the cost is
    // acceptable. A pre-built `card_id → first chunk index` map
    // would be cleaner but adds startup cost for the common (no-ID)
    // path; revisit if a profile shows this is hot.
    for (let i = 0; i < indexPages.length; i += 1) {
      const [card_id, page] = indexPages[i];
      if (card_id === id) {
        const pageRec = pagesMap.get(`${card_id}-p${page}`);
        out.push({
          card_id,
          page,
          title: pageRec?.title || "",
          snippet: makeSnippetFn(pageRec?.text || "", query),
          // Score sentinel: 1.0 puts the literal-ID hit ahead of any
          // realistic cosine score. Downstream consumers that surface
          // scores should treat ≥1.0 as "exact-match by ID, not by
          // similarity" rather than a confidence number.
          score: 1.0,
          page_text: pageRec?.text || "",
        });
        break;
      }
    }
  }
  return out;
}

/**
 * Merge literal-ID hits (lead) with semantic hits (tail). Dedup by
 * `${card_id}-p${page}` so a passage that wins both lanes appears once.
 * Cap at `k` entries.
 */
export function mergeLiteralAndSemantic(literal, semantic, k) {
  const seen = new Set();
  const out = [];
  for (const p of literal) {
    const key = `${p.card_id}-p${p.page}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(p);
    }
  }
  for (const p of semantic) {
    const key = `${p.card_id}-p${p.page}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(p);
    }
  }
  return out.slice(0, k);
}
