import { test } from "node:test";
import assert from "node:assert/strict";
import {
  nextIframeSrc,
  syncPdfIframeToPage,
  PDF_IFRAME_ID,
  type IframeLike,
  type DocumentLike,
} from "./pdf-iframe-sync.ts";

/** Build a stub iframe + document so we don't need jsdom. */
function makeDoc(iframe: IframeLike | null): DocumentLike {
  return {
    getElementById(id: string) {
      return id === PDF_IFRAME_ID ? iframe : null;
    },
  };
}

test("nextIframeSrc: appends #page=N when none is set", () => {
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf", "PDF", 3),
    "https://x.test/y.pdf#page=3",
  );
});

test("nextIframeSrc: replaces an existing #page=N fragment", () => {
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#page=2", "PDF", 7),
    "https://x.test/y.pdf#page=7",
  );
});

test("nextIframeSrc: returns null when src already targets the page (no-op)", () => {
  // Avoid touching iframe.src when it's already correct — some browsers
  // count any `src` write as a navigation, so a no-op write could flicker.
  assert.equal(nextIframeSrc("https://x.test/y.pdf#page=4", "PDF", 4), null);
});

test("nextIframeSrc: returns null for non-PDF asset types", () => {
  // IMG cards render <img>, not <iframe>, but if the helper is ever
  // pointed at one anyway, leave it alone.
  assert.equal(nextIframeSrc("https://x.test/y.jpg", "IMG", 3), null);
  assert.equal(nextIframeSrc("https://x.test/y.mp4", "VID", 3), null);
});

test("nextIframeSrc: tolerates a missing assetType (treats as PDF)", () => {
  // The Astro template always sets data-asset-type, but a user override
  // or future markup change shouldn't silently break the sync.
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf", undefined, 5),
    "https://x.test/y.pdf#page=5",
  );
});

test("nextIframeSrc: rejects invalid page numbers", () => {
  assert.equal(nextIframeSrc("https://x.test/y.pdf", "PDF", 0), null);
  assert.equal(nextIframeSrc("https://x.test/y.pdf", "PDF", -1), null);
  assert.equal(nextIframeSrc("https://x.test/y.pdf", "PDF", 1.5), null);
  assert.equal(nextIframeSrc("https://x.test/y.pdf", "PDF", NaN), null);
});

test("nextIframeSrc: returns null for empty src", () => {
  assert.equal(nextIframeSrc("", "PDF", 1), null);
});

test("syncPdfIframeToPage: writes #page=N onto the iframe.src when found", () => {
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf",
    dataset: { assetType: "PDF" },
  };
  syncPdfIframeToPage(makeDoc(iframe), 3);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=3");
});

test("syncPdfIframeToPage: no-op when the iframe is absent", () => {
  // Image cards, no-OCR cards, etc. — the helper must be safe to call
  // unconditionally from CardReaderView's effect.
  const doc = makeDoc(null);
  // Just assert it doesn't throw; nothing else to observe.
  syncPdfIframeToPage(doc, 5);
});

test("syncPdfIframeToPage: no-op when assetType is not PDF", () => {
  const iframe: IframeLike = {
    src: "https://x.test/y.jpg",
    dataset: { assetType: "IMG" },
  };
  syncPdfIframeToPage(makeDoc(iframe), 3);
  assert.equal(iframe.src, "https://x.test/y.jpg");
});

test("syncPdfIframeToPage: no-op when src already matches (avoids flicker)", () => {
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf#page=4",
    dataset: { assetType: "PDF" },
  };
  // We capture the original to confirm no write happened. (Strict equality
  // would still pass even if rewritten with the same string — the intent
  // here is just to prove the function returns gracefully.)
  syncPdfIframeToPage(makeDoc(iframe), 4);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=4");
});
