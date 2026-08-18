import { test } from "node:test";
import assert from "node:assert/strict";
import {
  reformatOcrText,
  readPageFromHash,
  readPageFromQuery,
  readPageFromLocation,
  pdfPageHref,
  clampPageIndex,
  loadReaderMode,
  saveReaderMode,
  READER_MODE_KEY,
  stripPageParam,
  promotedCardUrl,
} from "./reader-format.ts";

/** Minimal in-memory Storage shim — matches the Web Storage API surface
 *  loadReaderMode / saveReaderMode actually touch. */
function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() { return map.size; },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    removeItem: (k: string) => { map.delete(k); },
    setItem: (k: string, v: string) => { map.set(k, v); },
  };
}

test("reformatOcrText: empty input returns empty paragraphs", () => {
  assert.deepEqual(reformatOcrText(""), []);
  assert.deepEqual(reformatOcrText("   \n\n  \t  "), []);
});

test("reformatOcrText: blank line separates paragraphs; single newlines join", () => {
  const input = "line1\nline2\n\n\nline3";
  assert.deepEqual(reformatOcrText(input), ["line1 line2", "line3"]);
});

test("reformatOcrText: collapses runs of 3+ blank lines into a single break", () => {
  const input = "para one\n\n\n\n\npara two";
  assert.deepEqual(reformatOcrText(input), ["para one", "para two"]);
});

test("reformatOcrText: handles CRLF line endings", () => {
  const input = "alpha\r\nbravo\r\n\r\ncharlie";
  assert.deepEqual(reformatOcrText(input), ["alpha bravo", "charlie"]);
});

test("reformatOcrText: trims trailing whitespace and drops empty paragraphs", () => {
  const input = "  hello   world  \n\n   \n\nnext  ";
  assert.deepEqual(reformatOcrText(input), ["hello world", "next"]);
});

test("reformatOcrText: sparse text (e.g. a stamp) is preserved intact", () => {
  // Cards where the only OCR is a stamp like "TOP SECRET" must be preserved
  // verbatim — reader mode should not try to fluff this up.
  const input = "TOP SECRET\nTOP SECRET";
  assert.deepEqual(reformatOcrText(input), ["TOP SECRET TOP SECRET"]);
});

test("readPageFromHash: parses #page-N and rejects malformed input", () => {
  assert.equal(readPageFromHash("#page-1"), 1);
  assert.equal(readPageFromHash("#page-42"), 42);
  assert.equal(readPageFromHash("page-7"), 7); // tolerate missing leading #
  assert.equal(readPageFromHash(""), null);
  assert.equal(readPageFromHash(null), null);
  assert.equal(readPageFromHash("#provenance"), null);
  assert.equal(readPageFromHash("#page-"), null);
  assert.equal(readPageFromHash("#page-0"), null); // 1-indexed; reject 0
  assert.equal(readPageFromHash("#page-abc"), null);
});

test("pdfPageHref: appends PDF.js #page=N fragment", () => {
  assert.equal(
    pdfPageHref("https://www.war.gov/medialink/ufo/release_1/foo.pdf", 3),
    "https://www.war.gov/medialink/ufo/release_1/foo.pdf#page=3",
  );
});

test("pdfPageHref: rewrites only the page= key, leaving other fragment params intact", () => {
  // Updated contract (was: "strips any pre-existing fragment"). We now
  // preserve PDF.js viewer params like zoom/view so a zoom hint travels
  // with the page anchor. See also the dedicated preserve test below.
  assert.equal(
    pdfPageHref("https://example.com/x.pdf#zoom=100", 5),
    "https://example.com/x.pdf#page=5&zoom=100",
  );
});

test("pdfPageHref: returns null for empty url or invalid page", () => {
  assert.equal(pdfPageHref("", 1), null);
  assert.equal(pdfPageHref(null, 1), null);
  assert.equal(pdfPageHref(undefined, 1), null);
  assert.equal(pdfPageHref("https://x.test/y.pdf", 0), null);
  assert.equal(pdfPageHref("https://x.test/y.pdf", -2), null);
});

test("loadReaderMode: defaults to 'raw' when storage is empty or unavailable", () => {
  assert.equal(loadReaderMode(fakeStorage()), "raw");
  assert.equal(loadReaderMode(null), "raw");
});

test("loadReaderMode: returns persisted choice when valid", () => {
  const s = fakeStorage();
  s.setItem(READER_MODE_KEY, "reader");
  assert.equal(loadReaderMode(s), "reader");
  s.setItem(READER_MODE_KEY, "raw");
  assert.equal(loadReaderMode(s), "raw");
});

test("loadReaderMode: ignores garbage values, falls back to 'raw'", () => {
  const s = fakeStorage();
  s.setItem(READER_MODE_KEY, "purple");
  assert.equal(loadReaderMode(s), "raw");
});

test("loadReaderMode: recognizes 'cleaned' as a valid persisted mode", () => {
  // After the LLM-cleaned overlay shipped, "cleaned" joined the union.
  // The localStorage migration is implicit: any value not in the union
  // still falls back to "raw", so old browsers see no behavior change.
  const s = fakeStorage();
  s.setItem(READER_MODE_KEY, "cleaned");
  assert.equal(loadReaderMode(s), "cleaned");
});

test("saveReaderMode: round-trips 'cleaned' via loadReaderMode", () => {
  const s = fakeStorage();
  saveReaderMode(s, "cleaned");
  assert.equal(loadReaderMode(s), "cleaned");
});

test("saveReaderMode: round-trips via loadReaderMode", () => {
  const s = fakeStorage();
  saveReaderMode(s, "reader");
  assert.equal(s.getItem(READER_MODE_KEY), "reader");
  assert.equal(loadReaderMode(s), "reader");
  saveReaderMode(s, "raw");
  assert.equal(loadReaderMode(s), "raw");
});

test("saveReaderMode: tolerates a null storage (SSR / private mode)", () => {
  // Should not throw even when storage is unavailable.
  saveReaderMode(null, "reader");
});

test("readPageFromQuery: parses ?page=N from a query string", () => {
  // Forward-compat: nothing currently emits `?page=N`, but if a future
  // citation source does, the page should resolve. Hash always wins
  // (see readPageFromLocation) — this helper is purely query-side.
  assert.equal(readPageFromQuery("?page=3"), 3);
  assert.equal(readPageFromQuery("page=3"), 3); // tolerate missing leading ?
  assert.equal(readPageFromQuery("?q=foo&page=12"), 12);
  assert.equal(readPageFromQuery("?page=1&q=hi"), 1);
});

test("readPageFromQuery: returns null for malformed/missing values", () => {
  assert.equal(readPageFromQuery(""), null);
  assert.equal(readPageFromQuery(null), null);
  assert.equal(readPageFromQuery("?q=hello"), null);
  assert.equal(readPageFromQuery("?page="), null);
  assert.equal(readPageFromQuery("?page=0"), null); // 1-indexed
  assert.equal(readPageFromQuery("?page=abc"), null);
  assert.equal(readPageFromQuery("?page=-2"), null);
});

test("readPageFromLocation: hash takes precedence over query", () => {
  // The reader-mode contract: #page-N is the canonical anchor. ?page=N
  // is a fallback for external links that prefer queries; if both are
  // present, the hash wins so copy-pasted reader URLs stay deterministic.
  assert.equal(readPageFromLocation("#page-5", "?page=2"), 5);
  assert.equal(readPageFromLocation("#page-5", ""), 5);
  assert.equal(readPageFromLocation("", "?page=2"), 2);
  assert.equal(readPageFromLocation("", ""), null);
  assert.equal(readPageFromLocation(null, null), null);
  assert.equal(readPageFromLocation("#provenance", "?page=4"), 4);
});

test("stripPageParam: removes ?page=N from a query string and preserves other params", () => {
  // After promoteQueryToHash succeeds, the URL is rewritten to drop the
  // now-redundant `?page=N` so canonical shape is `/card/<id>#page-N`.
  // Other params (e.g. `q=...` from a citation chip) must survive.
  assert.equal(stripPageParam("?page=5"), "");
  assert.equal(stripPageParam("?page=5&q=foo"), "?q=foo");
  assert.equal(stripPageParam("?q=foo&page=5"), "?q=foo");
  assert.equal(stripPageParam("?q=foo&page=5&zoom=fit"), "?q=foo&zoom=fit");
});

test("stripPageParam: returns the input unchanged when ?page is absent", () => {
  assert.equal(stripPageParam(""), "");
  assert.equal(stripPageParam("?q=hello"), "?q=hello");
  assert.equal(stripPageParam(null), "");
  assert.equal(stripPageParam(undefined), "");
});

test("stripPageParam: handles a leading-?-less query string", () => {
  // mirrors readPageFromQuery's tolerance — internal callers might pass
  // either form depending on whether they sourced from window.location.search.
  assert.equal(stripPageParam("page=3&q=foo"), "?q=foo");
  assert.equal(stripPageParam("page=3"), "");
});

test("pdfPageHref: preserves non-page fragment params (zoom, view) when appending page", () => {
  // Citation chip "Read on war.gov" should preserve any zoom hint the
  // caller has on the asset_url. We only rewrite the `page=` key.
  assert.equal(
    pdfPageHref("https://example.com/x.pdf#zoom=fit", 5),
    "https://example.com/x.pdf#page=5&zoom=fit",
  );
  assert.equal(
    pdfPageHref("https://example.com/x.pdf#page=2&zoom=100", 5),
    "https://example.com/x.pdf#page=5&zoom=100",
  );
});

test("readPageFromQuery: returns null without throwing for genuinely odd input (no dead catch)", () => {
  // URLSearchParams in modern Node/Chromium does not throw on weird input —
  // it just yields nothing for missing keys. This test documents that
  // contract so a future refactor doesn't reintroduce a defensive catch.
  assert.equal(readPageFromQuery("?%ZZ"), null);
  assert.equal(readPageFromQuery("?page=3&page=4"), 3);
});

test("promotedCardUrl: only ?page=N → /card/<id>#page-N (drops the query)", () => {
  // External link with no hash: promote the query to a hash and drop
  // the now-redundant `?page=N`.
  assert.equal(
    promotedCardUrl("/card/abc", "?page=5", ""),
    "/card/abc#page-5",
  );
});

test("promotedCardUrl: keeps non-page query params when promoting", () => {
  // `?q=foo&page=5` → `/card/abc?q=foo#page-5`. Drop only `page`.
  assert.equal(
    promotedCardUrl("/card/abc", "?q=foo&page=5", ""),
    "/card/abc?q=foo#page-5",
  );
});

test("promotedCardUrl: ?page=5#page-5 → /card/<id>#page-5 (hash already present)", () => {
  // Atlas link arrives with both forms. Hash is already authoritative;
  // strip the redundant query so the canonical URL is what the user copies.
  assert.equal(
    promotedCardUrl("/card/abc", "?page=5", "#page-5"),
    "/card/abc#page-5",
  );
});

test("promotedCardUrl: ?page=5&q=foo#page-5 → /card/<id>?q=foo#page-5", () => {
  // Hash present + non-page query params → drop only `?page` from the query.
  assert.equal(
    promotedCardUrl("/card/abc", "?q=foo&page=5", "#page-5"),
    "/card/abc?q=foo#page-5",
  );
});

test("promotedCardUrl: returns null when no normalization is needed", () => {
  // No `?page` in query → nothing to do; bootstrap should skip replaceState.
  // We return null so the caller can branch cheaply rather than compare strings.
  assert.equal(promotedCardUrl("/card/abc", "", ""), null);
  assert.equal(promotedCardUrl("/card/abc", "?q=foo", ""), null);
  assert.equal(promotedCardUrl("/card/abc", "", "#page-5"), null);
  assert.equal(promotedCardUrl("/card/abc", "?q=foo", "#page-5"), null);
});

test("promotedCardUrl: hash with non-page anchor is preserved", () => {
  // /card/abc?page=5#provenance — hash isn't a page anchor, but the
  // query still gets canonicalized (drop ?page=5, keep the hash).
  // Either decision is defensible; we currently treat it as "promote
  // wins" since the user landed via an external `?page=5` link, so
  // we rewrite the hash to match. Document whichever choice.
  // CHOICE: hash wins when present at all. Drop only the redundant query.
  assert.equal(
    promotedCardUrl("/card/abc", "?page=5", "#provenance"),
    "/card/abc#provenance",
  );
});

test("clampPageIndex: clamps to [1, total] and falls back to 1", () => {
  assert.equal(clampPageIndex(1, 5), 1);
  assert.equal(clampPageIndex(5, 5), 5);
  assert.equal(clampPageIndex(99, 5), 5);
  assert.equal(clampPageIndex(0, 5), 1);
  assert.equal(clampPageIndex(-3, 5), 1);
  assert.equal(clampPageIndex(null, 5), 1);
  assert.equal(clampPageIndex(NaN, 5), 1);
  // Edge: total=0 (no pages) — returns 1 so callers can treat as "no-op";
  // Reader mode is hidden in that case anyway.
  assert.equal(clampPageIndex(2, 0), 1);
});
