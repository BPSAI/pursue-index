import { test } from "node:test";
import assert from "node:assert/strict";
import MiniSearch from "minisearch";
import {
  buildSearchIndexOptions,
  highlightSegments,
  hasMatchSegment,
} from "./search-result-highlight.ts";
import { buildHighlightRegex, tokenize } from "./highlight.ts";

interface PageDoc {
  id: string;
  card_id: string;
  page: number;
  title: string;
  text: string;
}

/**
 * Build a MiniSearch instance configured exactly like SearchIsland's
 * production index so this test exercises the real search behavior.
 */
function buildIndex(docs: PageDoc[]): MiniSearch<PageDoc> {
  const ms = new MiniSearch<PageDoc>(buildSearchIndexOptions<PageDoc>());
  ms.addAll(docs);
  return ms;
}

const docs: PageDoc[] = [
  {
    id: "a-p1",
    card_id: "a",
    page: 1,
    title: "DOW-UAP-D54 Arabian Gulf Sighting",
    text: "Witnesses observed an object over open water at dusk.",
  },
  {
    id: "b-p1",
    card_id: "b",
    page: 1,
    title: "Yellow Area Anomaly Report",
    text: "Sample of unidentified phenomena from the yellow area.",
  },
  {
    id: "c-p1",
    card_id: "c",
    page: 1,
    title: "Red Zone Briefing",
    text: "Red zone activity across the corridor with no yellow signal.",
  },
  {
    id: "d-p1",
    card_id: "d",
    page: 1,
    title: "Greenfield Survey",
    text: "Open area observation with no other markers of interest.",
  },
  {
    // Fuzzy trap: "mellow" and "arena" are both within edit-distance 1 of
    // "yellow" and "area". Under fuzzy: 0.2 (the old config), MiniSearch
    // returns this doc for the query "yellow area" even though it contains
    // neither term literally. Without fuzzy, it should NOT appear.
    id: "ft-p1",
    card_id: "ft",
    page: 1,
    title: "Mellow Arena Notes",
    text: "A mellow tune played in the arena before the briefing.",
  },
];

// ---------------------------------------------------------------------------
// Cycle 1: AND-combined multi-term queries don't fuzzy-expand.
// ---------------------------------------------------------------------------

test("multi-term query 'yellow area' returns only docs containing BOTH terms", () => {
  const ms = buildIndex(docs);
  const hits = ms.search("yellow area", { combineWith: "AND" });
  const ids = hits.map((h) => h.id).sort();
  // Doc b has both. Doc c has only "yellow". Doc d has only "area". Without
  // fuzzy expansion, the AND intersection should fire only on doc b.
  assert.deepEqual(ids, ["b-p1"]);
});

test("prefix match still works (fuzzy was dropped, prefix retained)", () => {
  const ms = buildIndex([
    { id: "x-p1", card_id: "x", page: 1, title: "UAPs over Pacific", text: "uap_d54 sighting" },
  ]);
  const hits = ms.search("uap", { combineWith: "AND" });
  assert.equal(hits.length, 1, "prefix expansion of 'uap' should still match 'UAPs'");
});

// ---------------------------------------------------------------------------
// Cycle 2: Title gets run through the highlight pipeline.
// ---------------------------------------------------------------------------

test("title containing query term is split into match + text segments", () => {
  const regex = buildHighlightRegex(tokenize("arabian uap"));
  const segs = highlightSegments("DOW-UAP-D54 Arabian Gulf Sighting", regex);
  const matches = segs.filter((s) => s.kind === "match").map((s) => s.value.toLowerCase());
  assert.ok(matches.includes("uap"), "title 'UAP' token should highlight");
  assert.ok(matches.includes("arabian"), "title 'Arabian' token should highlight");
});

test("title with no query overlap yields no match segments", () => {
  const regex = buildHighlightRegex(tokenize("zeppelin"));
  const segs = highlightSegments("Arabian Gulf Sighting", regex);
  assert.equal(segs.filter((s) => s.kind === "match").length, 0);
});

// ---------------------------------------------------------------------------
// Cycle 3: hasMatchSegment correctly identifies title-only matches so the
// snippet block can be suppressed.
// ---------------------------------------------------------------------------

test("hasMatchSegment is false when snippet contains no matches (title-only hit)", () => {
  const regex = buildHighlightRegex(tokenize("arabian"));
  // Body text has no "arabian" — only the title would. Simulates buildSnippet
  // falling back to the head of text.
  const snippet = "Witnesses observed an object over open water at dusk.";
  const segs = highlightSegments(snippet, regex);
  assert.equal(hasMatchSegment(segs), false);
});

test("hasMatchSegment is true when snippet contains at least one match", () => {
  const regex = buildHighlightRegex(tokenize("water"));
  const snippet = "Witnesses observed an object over open water at dusk.";
  const segs = highlightSegments(snippet, regex);
  assert.equal(hasMatchSegment(segs), true);
});

test("hasMatchSegment handles empty regex (no query)", () => {
  const segs = highlightSegments("anything", null);
  assert.equal(hasMatchSegment(segs), false);
});

// ---------------------------------------------------------------------------
// Cycle 4: buildSearchIndexOptions is the single config factory shared by
// /search and /atlas. The override hook lets atlas plug a wider doc shape
// in without redeclaring the shared options (boost / prefix / no-fuzzy).
// PR #29 — keep configs structurally locked, not by comment.
// ---------------------------------------------------------------------------

test("buildSearchIndexOptions returns the canonical defaults when no overrides", () => {
  const opts = buildSearchIndexOptions<PageDoc>();
  assert.deepEqual(opts.fields, ["title", "text"]);
  assert.deepEqual(opts.storeFields, ["card_id", "page", "title"]);
  assert.equal(opts.idField, "id");
  assert.deepEqual(opts.searchOptions?.boost, { title: 2 });
  assert.equal(opts.searchOptions?.prefix, true);
  // The whole point of PR #29 — fuzzy must not be silently re-introduced.
  assert.ok(
    !("fuzzy" in (opts.searchOptions ?? {})),
    "fuzzy must remain absent (operator decision 2026-05-10)",
  );
});

test("buildSearchIndexOptions allows overriding fields and storeFields", () => {
  // Atlas indexes a different doc shape (numeric id, no card_id/page on the
  // doc itself) and stores only its render-array index — so it needs to
  // override storeFields without losing the no-fuzzy / boost / prefix
  // contract baked into the factory.
  interface AtlasDocLike {
    id: number;
    title: string;
    text: string;
  }
  const opts = buildSearchIndexOptions<AtlasDocLike>({
    storeFields: ["id"],
  });
  assert.deepEqual(opts.storeFields, ["id"]);
  // Defaults preserved through the override path.
  assert.deepEqual(opts.fields, ["title", "text"]);
  assert.deepEqual(opts.searchOptions?.boost, { title: 2 });
  assert.equal(opts.searchOptions?.prefix, true);
  assert.ok(
    !("fuzzy" in (opts.searchOptions ?? {})),
    "fuzzy must remain absent even when overrides are passed",
  );
});

test("buildSearchIndexOptions overrides apply to a real MiniSearch instance", () => {
  // End-to-end: feed the factory output into MiniSearch and confirm atlas's
  // narrower storeFields actually take effect at query time. Regression guard
  // for the case where a future edit re-adds fuzzy in one path but not the
  // other and the two surfaces drift again.
  interface AtlasDocLike {
    id: number;
    title: string;
    text: string;
  }
  const ms = new MiniSearch<AtlasDocLike>(
    buildSearchIndexOptions<AtlasDocLike>({ storeFields: ["id"] }),
  );
  ms.addAll([
    { id: 0, title: "Mellow Arena Notes", text: "mellow tune in the arena" },
    { id: 1, title: "Yellow Area Anomaly", text: "yellow area report" },
  ]);
  const hits = ms.search("yellow area", { combineWith: "AND" });
  // Same fuzzy-trap assertion as the /search side — confirms atlas now
  // inherits the no-fuzzy guarantee from the shared factory.
  assert.deepEqual(hits.map((h) => h.id), [1]);
});
