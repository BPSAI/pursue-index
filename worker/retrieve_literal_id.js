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
//
// nayru P1#3 note: this regex ALSO matches pure-digit 16-character
// strings (a phone or case number), because hex digits include 0-9.
// That's a benign false-positive in practice: `literalIdPassages`
// silently drops unknown IDs not in the corpus index, so a 16-digit
// numeric token in a user query triggers a no-op lookup and falls
// through to the semantic search lane. We deliberately do NOT tighten
// the pattern to require at least one a-f character: the 16-hex
// canonical card_ids that DO live in the corpus might happen to be
// all-numeric (the SHA prefix has uniform digit distribution; ~1/16⁻⁰
// of card_ids would be all-digits over the long run). Locking the
// behavior in test coverage prevents accidental tightening.
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
 * nayru P2#2 note: this only emits the FIRST chunk per card_id (the
 * `break` after the first match exits the inner loop). For a
 * multi-page card, page 1 is always prepended; subsequent pages
 * surface only via the semantic-search tail when they cosine-match
 * the rest of the query. That matches the intent of the literal-ID
 * lookup ("show me card X") — page 1 is the canonical anchor and the
 * chat model can pull additional pages on follow-up via the same
 * mechanism. Revisit if multi-page literal-ID expansion becomes a
 * recurring miss in chat traces.
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

// ---------------------------------------------------------------------------
// Sprint 4 follow-up — agency-prefixed D/PR/VM slug bypass (Option C).
//
// Companion to LITERAL_CARD_ID_RE for the OTHER common literal-lookup
// shape in this corpus: title-form slugs like DOW-UAP-D017 /
// CIA-UAP-D001 / NASA-UAP-VM001. Decision rationale, alternative
// options, and trigger conditions for revisiting are in
// findings/2026-06-02-chat-retrieval-d-pattern-bypass-and-telemetry-gap.md.
//
// Canonical form: AGENCY-CODE (UAP middle token dropped — it's noise;
// every code in this corpus is UAP-themed). Examples:
//   `DOW-UAP-D017` → `DOW-D017`
//   `dow uap d017` → `DOW-D017`
//   `DOW/UAP/D017` → `DOW-D017`
//   `DOW-D017`     → `DOW-D017` (already canonical)
//
// Bare codes (`D017` alone, no agency) are deliberately NOT detected:
// `D001` is ambiguous across three agencies (DOE-UAP-D001 /
// CIA-UAP-D001 / ODNI-UAP-D001), and the semantic embedding handles
// in-context queries well. The 16-hex lane is the answer for users
// who know the canonical card_id.
// ---------------------------------------------------------------------------

// Agency-prefixed slug pattern. Constraints:
//   * `[A-Z]{2,5}` — agency token (DOW / CIA / NASA / ODNI / DOE)
//   * `[-/]`        — separator (dash or slash). NOT whitespace —
//     the case-insensitive `[A-Z]{2,5}` would otherwise match
//     English words like "about" / "tell" in casual prose and create
//     false positives on phrases like "tell me about D017". Users
//     who type slugs read them from URLs / card-detail pages, which
//     are dash-separated.
//   * `(?:UAP[-/])?` — optional UAP middle token (corpus convention,
//                      dropped on canonicalization)
//   * `(D|PR|VM)\d{2,4}` — code prefix + 2-4 digit number
// `\b` word boundaries on both sides reject substrings of longer tokens
// (e.g. `XCIA-UAP-D001Y`). Case-insensitive match; canonical output is
// uppercase with single dashes.
export const LITERAL_SLUG_RE =
  /\b[A-Z]{2,5}[-/](?:UAP[-/])?(?:D|PR|VM)\d{2,4}\b/gi;

/**
 * Normalize a matched slug substring to the canonical `AGENCY-CODE`
 * form used as the slug-index Map key. Drops UAP, collapses
 * separators to single dashes, uppercases.
 */
function canonicalizeSlug(match) {
  return match
    .toUpperCase()
    .replace(/[/]/g, "-")
    .replace(/-UAP-/g, "-")
    .replace(/^UAP-/, "");
}

/**
 * Extract canonicalized agency-prefixed slugs from a free-form user
 * query.
 *
 * Returns an order-preserving, deduped list. Bare codes without an
 * agency prefix are NOT extracted (Option C: ambiguity guard).
 *
 * Companion to `extractLiteralCardIds` — feeds the same prepend-then-
 * merge pipeline in `retrievePassages`.
 */
export function extractLiteralSlugs(query) {
  if (typeof query !== "string" || !query) return [];
  const seen = new Set();
  const out = [];
  for (const match of query.matchAll(LITERAL_SLUG_RE)) {
    const canonical = canonicalizeSlug(match[0]);
    if (!seen.has(canonical)) {
      seen.add(canonical);
      out.push(canonical);
    }
  }
  return out;
}

/**
 * Build a `Map<canonicalSlug, card_id>` from the pages cache.
 *
 * Scans every page's title for matching slugs (same regex as
 * `extractLiteralSlugs`); the first card_id seen for a given slug
 * wins. The pages cache stores one entry per (card_id, page); titles
 * are identical across pages of a card, so subsequent matches for the
 * same slug are no-ops via Map's overwrite semantics (same card_id).
 *
 * Built once at corpus-load time, cached for the worker lifetime.
 * Cost is ~O(pages × titleLength); negligible at corpus scale (~4k
 * pages, short titles).
 */
export function buildSlugIndex(pagesMap) {
  const index = new Map();
  for (const pageRec of pagesMap.values()) {
    const title = pageRec?.title || "";
    if (!title) continue;
    for (const match of title.matchAll(LITERAL_SLUG_RE)) {
      const canonical = canonicalizeSlug(match[0]);
      if (!index.has(canonical)) {
        index.set(canonical, pageRec.card_id);
      }
    }
  }
  return index;
}

/**
 * Build the slug-lookup prepend list. For each canonical slug in
 * `slugs`, resolve it to a `card_id` via `slugIndex`, then find that
 * card's first chunk in `indexPages` and emit a passage record.
 * Unknown slugs (no match in the index) are silently skipped — same
 * fallthrough policy as `literalIdPassages`.
 *
 * Score sentinel matches `literalIdPassages` (1.0) so slug hits and
 * hex hits sit on equal footing ahead of any semantic cosine score;
 * mention order in the query determines which lands first via
 * `mergeLiteralAndSemantic`'s dedup-preserving merge.
 */
export function literalSlugPassages(
  slugs,
  slugIndex,
  indexPages,
  pagesMap,
  query,
  makeSnippetFn,
) {
  const out = [];
  for (const slug of slugs) {
    const cardId = slugIndex.get(slug);
    if (!cardId) continue;
    for (let i = 0; i < indexPages.length; i += 1) {
      const [card_id, page] = indexPages[i];
      if (card_id === cardId) {
        const pageRec = pagesMap.get(`${card_id}-p${page}`);
        out.push({
          card_id,
          page,
          title: pageRec?.title || "",
          snippet: makeSnippetFn(pageRec?.text || "", query),
          score: 1.0,
          page_text: pageRec?.text || "",
        });
        break;
      }
    }
  }
  return out;
}
