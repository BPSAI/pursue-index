import { test } from "node:test";
import assert from "node:assert/strict";
import {
  reformatOcrText,
  readPageFromHash,
  readPageFromQuery,
  readPageFromLocation,
  pdfPageHref,
  buildPdfIframeSrc,
  clampPageIndex,
  loadReaderMode,
  saveReaderMode,
  READER_MODE_KEY,
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
  // The redditor critique called out cards where the only OCR is a stamp
  // like "TOP SECRET" — reader mode should not try to fluff this up.
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

test("pdfPageHref: strips any pre-existing fragment", () => {
  assert.equal(
    pdfPageHref("https://example.com/x.pdf#zoom=100", 5),
    "https://example.com/x.pdf#page=5",
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

test("buildPdfIframeSrc: appends #page=N to PDF urls", () => {
  // PDF.js and most native browser viewers honor `#page=N` in iframe src.
  assert.equal(
    buildPdfIframeSrc("https://www.war.gov/foo.pdf", 3, "PDF"),
    "https://www.war.gov/foo.pdf#page=3",
  );
});

test("buildPdfIframeSrc: returns the bare url when page is null/invalid", () => {
  // Page null = no anchor desired (e.g. user landed on /card/<id> with no hash).
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.pdf", null, "PDF"),
    "https://x.test/y.pdf",
  );
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.pdf", 0, "PDF"),
    "https://x.test/y.pdf",
  );
});

test("buildPdfIframeSrc: skips the fragment for non-PDF cards (IMG/VID)", () => {
  // Image cards render the asset_url in an <img>, not an <iframe>, but if
  // a future caller still wires this for IMG/VID we should not pollute
  // the URL with a meaningless #page=N.
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.jpg", 3, "IMG"),
    "https://x.test/y.jpg",
  );
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.mp4", 3, "VID"),
    "https://x.test/y.mp4",
  );
});

test("buildPdfIframeSrc: returns null when the source URL is missing", () => {
  assert.equal(buildPdfIframeSrc(null, 3, "PDF"), null);
  assert.equal(buildPdfIframeSrc("", 3, "PDF"), null);
  assert.equal(buildPdfIframeSrc(undefined, 3, "PDF"), null);
});

test("buildPdfIframeSrc: replaces an existing #page=N fragment, preserves bare hash", () => {
  // If asset_url already includes a stale `#page=2` from a prior nav,
  // overwrite with the new page rather than concatenating.
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.pdf#page=2", 7, "PDF"),
    "https://x.test/y.pdf#page=7",
  );
  // But leave non-page fragments alone (e.g. `#zoom=fit` from a manual hand-edit).
  // Simpler: we strip and replace — the asset_url isn't expected to carry zoom hints.
  assert.equal(
    buildPdfIframeSrc("https://x.test/y.pdf#zoom=100", 7, "PDF"),
    "https://x.test/y.pdf#page=7",
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
