import { test } from "node:test";
import assert from "node:assert/strict";
import {
  nextIframeSrc,
  syncPdfIframeToPage,
  createDebouncedPdfIframeSync,
  PDF_IFRAME_ID,
  type IframeLike,
  type DocumentLike,
} from "./pdf-iframe-sync.ts";

/** A controllable clock so debounce tests don't sleep. */
function fakeClock() {
  let now = 0;
  const queue: Array<{ at: number; fn: () => void; id: number }> = [];
  let nextId = 1;
  return {
    setTimeout(fn: () => void, delay: number): number {
      const id = nextId++;
      queue.push({ at: now + delay, fn, id });
      return id;
    },
    clearTimeout(id: number) {
      const idx = queue.findIndex((q) => q.id === id);
      if (idx >= 0) queue.splice(idx, 1);
    },
    advance(ms: number) {
      now += ms;
      // Drain any timer that's now due, in scheduled order.
      while (true) {
        const due = queue.findIndex((q) => q.at <= now);
        if (due === -1) break;
        const [item] = queue.splice(due, 1);
        item.fn();
      }
    },
  };
}

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

test("nextIframeSrc: rejects non-https protocols (javascript:, data:, http:, file:)", () => {
  // SEC-002: a malformed manifest entry could ship a hostile asset_url
  // (e.g. `javascript:alert(1)`). We refuse to assemble a navigable iframe
  // src from anything but https — eliminates the XSS class permanently.
  assert.equal(nextIframeSrc("javascript:alert(1)", "PDF", 3), null);
  assert.equal(nextIframeSrc("data:text/html,<script>1</script>", "PDF", 3), null);
  assert.equal(nextIframeSrc("http://x.test/y.pdf", "PDF", 3), null);
  assert.equal(nextIframeSrc("file:///etc/passwd", "PDF", 3), null);
});

test("nextIframeSrc: preserves non-page fragment params (zoom, view) when replacing page", () => {
  // PDF.js viewer params live alongside `page=N` in the fragment; only
  // the `page=` key should be rewritten. Order is normalized so the new
  // page lands first, keeping the rest intact.
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#zoom=fit&page=2", "PDF", 7),
    "https://x.test/y.pdf#page=7&zoom=fit",
  );
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#page=2&view=FitH", "PDF", 9),
    "https://x.test/y.pdf#page=9&view=FitH",
  );
});

test("nextIframeSrc: appends page= alongside an existing non-page fragment", () => {
  // If the iframe already carries `#zoom=100` (e.g. the user fiddled in the
  // viewer and PDF.js wrote it), syncing to page 4 should yield the merged
  // form, not clobber the zoom hint.
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#zoom=100", "PDF", 4),
    "https://x.test/y.pdf#page=4&zoom=100",
  );
});

test("nextIframeSrc: same-origin /pdf/<id>.pdf URLs are accepted and rewritten the same way", () => {
  // After the war.gov framing fix (PR #27), the iframe src is now
  // a same-origin route (`/pdf/<card_id>.pdf` served by worker/pdf.js
  // off the `pursue-pdfs` R2 bucket). Lock the contract: the helper
  // must rewrite these URLs identically to the legacy war.gov ones,
  // so a future SSR refactor can't silently regress page-sync.
  const sameOrigin = "https://pursueindex.com/pdf/abcdef0123456789.pdf";
  // No existing fragment → page= is appended.
  assert.equal(
    nextIframeSrc(sameOrigin, "PDF", 3),
    `${sameOrigin}#page=3`,
  );
  // Existing #page=N → replaced.
  assert.equal(
    nextIframeSrc(`${sameOrigin}#page=2`, "PDF", 7),
    `${sameOrigin}#page=7`,
  );
  // Same-page no-op still detected with the new URL shape.
  assert.equal(nextIframeSrc(`${sameOrigin}#page=4`, "PDF", 4), null);
  // Extra viewer params (zoom) survive a page rewrite.
  assert.equal(
    nextIframeSrc(`${sameOrigin}#zoom=fit&page=2`, "PDF", 9),
    `${sameOrigin}#page=9&zoom=fit`,
  );
});

test("nextIframeSrc: returns null when page already matches even with extra fragment params", () => {
  // Same-page no-op must still trigger when other params are present so we
  // don't reorder/rewrite for a no-change navigation.
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#page=4&zoom=fit", "PDF", 4),
    null,
  );
  assert.equal(
    nextIframeSrc("https://x.test/y.pdf#zoom=fit&page=4", "PDF", 4),
    null,
  );
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

test("syncPdfIframeToPage: writes correctly across a multi-page sequence (2 → 3 → 5)", () => {
  // Realistic j/j/j scenario: each call should advance the iframe to the
  // requested page. No accidental reordering, no leftover fragments.
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf",
    dataset: { assetType: "PDF" },
  };
  const doc = makeDoc(iframe);
  syncPdfIframeToPage(doc, 2);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=2");
  syncPdfIframeToPage(doc, 3);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=3");
  syncPdfIframeToPage(doc, 5);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=5");
});

test("syncPdfIframeToPage: IMG card iframe is left untouched at the DOM layer", () => {
  // Belt-and-suspenders: nextIframeSrc already gates on assetType, but the
  // DOM helper is what runtime calls — verify the gate composes through.
  const iframe: IframeLike = {
    src: "https://x.test/y.jpg",
    dataset: { assetType: "IMG" },
  };
  const before = iframe.src;
  syncPdfIframeToPage(makeDoc(iframe), 3);
  syncPdfIframeToPage(makeDoc(iframe), 7);
  assert.equal(iframe.src, before);
});

test("syncPdfIframeToPage: hostile asset_url (javascript:) is refused at the DOM layer", () => {
  // SEC-002 defense-in-depth: even if the manifest somehow ships a
  // javascript: URL into data-asset-url, the DOM helper must NOT
  // synthesize an iframe.src write.
  const iframe: IframeLike = {
    src: "javascript:alert(1)",
    dataset: { assetType: "PDF" },
  };
  syncPdfIframeToPage(makeDoc(iframe), 3);
  assert.equal(iframe.src, "javascript:alert(1)");
});

test("createDebouncedPdfIframeSync: coalesces rapid j/k presses into a single iframe write", () => {
  // Setting iframe.src is a navigation in Chrome/Safari (it re-fetches
  // the cross-origin doc). Rapid `j j j` should not trigger three
  // reloads — only the final page should be written after the debounce.
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf",
    dataset: { assetType: "PDF" },
  };
  const doc = makeDoc(iframe);
  const clock = fakeClock();
  const sync = createDebouncedPdfIframeSync(doc, 250, {
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
  });
  sync(2);
  sync(3);
  sync(5);
  // Before the debounce window elapses, no write should have happened.
  assert.equal(iframe.src, "https://x.test/y.pdf");
  clock.advance(249);
  assert.equal(iframe.src, "https://x.test/y.pdf");
  clock.advance(1);
  // After 250ms total, only the LAST requested page is written.
  assert.equal(iframe.src, "https://x.test/y.pdf#page=5");
});

test("createDebouncedPdfIframeSync: a write that lands during a quiet period fires after the delay", () => {
  // Single press → fires once after the delay.
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf",
    dataset: { assetType: "PDF" },
  };
  const clock = fakeClock();
  const sync = createDebouncedPdfIframeSync(makeDoc(iframe), 250, {
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
  });
  sync(7);
  clock.advance(250);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=7");
});

test("createDebouncedPdfIframeSync: separate bursts each produce one write", () => {
  // First burst (pages 2,3) → write page 3. Then another burst (5,8)
  // after the window closes → write page 8.
  const iframe: IframeLike = {
    src: "https://x.test/y.pdf",
    dataset: { assetType: "PDF" },
  };
  const clock = fakeClock();
  const sync = createDebouncedPdfIframeSync(makeDoc(iframe), 250, {
    setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
    clearTimeout: (id) => clock.clearTimeout(id),
  });
  sync(2);
  sync(3);
  clock.advance(250);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=3");
  sync(5);
  sync(8);
  clock.advance(250);
  assert.equal(iframe.src, "https://x.test/y.pdf#page=8");
});
