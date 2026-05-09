import { test } from "node:test";
import assert from "node:assert/strict";
import {
  reformatOcrText,
  readPageFromHash,
  pdfPageHref,
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
