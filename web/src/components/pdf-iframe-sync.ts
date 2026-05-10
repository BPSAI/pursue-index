/**
 * Helper that keeps the embedded PDF viewer iframe on `/card/<id>` in
 * sync with the reader-mode active page. Lives in its own module so it
 * stays unit-testable without a real browser DOM.
 *
 * Why we need this:
 *   PDF.js and most browser-native PDF viewers honor `#page=N` in the
 *   iframe `src`. The reader-mode component (CardReaderView) updates
 *   the parent URL via `history.replaceState`, which deliberately does
 *   NOT fire `hashchange`, so an event-listener-based sync inside the
 *   iframe never wakes up. Instead, the reader calls this helper after
 *   each page change.
 *
 * Why we mutate `src` (not `contentWindow.location.hash`):
 *   PDFs are now served same-origin from `/pdf/<card_id>.pdf` (worker/pdf.js
 *   off the `pursue-pdfs` R2 bucket), so `contentWindow.location.hash`
 *   would no longer throw SecurityError. We still rewrite `src` because
 *   that's what the existing test suite locks (see pdf-iframe-sync.test.ts)
 *   and the migration story is "framing fix only, no behavior change for
 *   the page-sync path." A future improvement could switch to mutating
 *   `iframe.contentWindow.location.hash` for a flash-free page jump now
 *   that same-origin permits it — that's a deliberate follow-up, not a
 *   blocker for the framing fix.
 *
 * Honest perf note (do not pretend otherwise):
 *   Assigning `iframe.src` is treated by Chromium and WebKit as a
 *   navigation, even when only the fragment changes — the iframe
 *   document re-fetches and re-renders. Firefox is more lenient but
 *   still inconsistent. Users will see a brief flash on each j/k.
 *   We accept this cost for now (the iframe-flash predates the framing
 *   fix; switching to `contentWindow.location.hash` is the follow-up
 *   that would actually eliminate it) and mitigate by:
 *     1. The `current === target` guard below — never write the same
 *        src twice in a row.
 *     2. Debouncing rapid page changes — see `syncPdfIframeToPageDebounced`.
 *     3. PDFs are byte-cached after first fetch, so subsequent reloads
 *        are layout-only, not network.
 */

/** The minimal HTMLIFrameElement surface this module touches — keeps tests DOM-free. */
export interface IframeLike {
  src: string;
  dataset: DOMStringMap | { assetType?: string };
}

/** A document-shaped lookup so callers can pass `document` or a stub. */
export interface DocumentLike {
  getElementById(id: string): IframeLike | null;
}

/** The id we apply to the embedded PDF iframe in `[card_id].astro`. */
export const PDF_IFRAME_ID = "card-pdf-iframe";

/**
 * Compute the new src for an iframe given the desired page. Returns null
 * when the iframe should not be touched (non-PDF asset, missing/non-https
 * src, or the src is already on the right page).
 *
 * Preserves non-`page=` PDF.js viewer params (zoom, view, ...) when
 * rewriting the fragment so a user-set zoom level survives a page jump.
 *
 * Refuses non-https schemes (defense-in-depth): post-PR #27 the iframe
 * src is built from `card.card_id` server-side, and `card_id` is
 * regex-validated as `^[a-f0-9]{16}$` by both the worker (worker/pdf.js)
 * and the manifest builder, so the original SEC-002 concern about a
 * hostile `asset_url` slipping through no longer applies on the live
 * code path. We keep the `https://` startsWith guard because a future
 * refactor could reintroduce a code path that derives src from a
 * less-validated field, and refusing non-https here costs nothing —
 * `nextIframeSrc` returning null makes the helper a no-op rather than
 * letting it synthesize a hostile URL.
 *
 * Exported for testing; the runtime helper below composes this with the
 * DOM lookup.
 */
export function nextIframeSrc(
  current: string,
  assetType: string | undefined,
  page: number,
): string | null {
  if (!current) return null;
  if (!current.startsWith("https://")) return null;
  if (assetType && assetType !== "PDF") return null;
  if (!Number.isInteger(page) || page < 1) return null;
  const hashIdx = current.indexOf("#");
  const base = hashIdx === -1 ? current : current.slice(0, hashIdx);
  const fragment = hashIdx === -1 ? "" : current.slice(hashIdx + 1);
  const params = parsePdfFragment(fragment);
  const existingPage = params.get("page");
  if (existingPage === String(page)) return null;
  // Rewrite `page=` first so the new value is the canonical leading param;
  // keep all other keys (zoom, view, nameddest, ...) in their original order.
  const out = new Map<string, string>();
  out.set("page", String(page));
  for (const [k, v] of params) {
    if (k !== "page") out.set(k, v);
  }
  return `${base}#${serializePdfFragment(out)}`;
}

/**
 * Parse a PDF.js viewer fragment (e.g. `page=2&zoom=fit&view=FitH`) into
 * an ordered Map. Keeps insertion order so re-serializing a no-op fragment
 * is byte-identical. We DO NOT use URLSearchParams here because it would
 * reorder/percent-encode keys and break PDF.js's lenient parser.
 */
function parsePdfFragment(fragment: string): Map<string, string> {
  const out = new Map<string, string>();
  if (!fragment) return out;
  for (const part of fragment.split("&")) {
    if (!part) continue;
    const eq = part.indexOf("=");
    if (eq === -1) {
      // Bare token like `#zoom` (no value). Preserve as empty string.
      if (!out.has(part)) out.set(part, "");
    } else {
      const k = part.slice(0, eq);
      const v = part.slice(eq + 1);
      if (k && !out.has(k)) out.set(k, v);
    }
  }
  return out;
}

function serializePdfFragment(params: Map<string, string>): string {
  const parts: string[] = [];
  for (const [k, v] of params) {
    parts.push(v === "" ? k : `${k}=${v}`);
  }
  return parts.join("&");
}

/**
 * Find the embedded PDF iframe (by id) and update its `src` so the
 * native viewer jumps to `page`. No-ops when the iframe is absent (image
 * cards, no-OCR cards, or pages that don't render a viewer).
 */
export function syncPdfIframeToPage(doc: DocumentLike, page: number): void {
  const iframe = doc.getElementById(PDF_IFRAME_ID);
  if (!iframe) return;
  const ds = iframe.dataset as { assetType?: string };
  const next = nextIframeSrc(iframe.src, ds.assetType, page);
  if (next != null) {
    iframe.src = next;
  }
}

/** Minimal timer-API surface so tests can drive a fake clock. */
export interface DebounceTimers {
  setTimeout: (fn: () => void, ms: number) => number;
  clearTimeout: (id: number) => void;
}

/**
 * Build a debounced version of `syncPdfIframeToPage`. Multiple `sync(n)`
 * calls within `delayMs` collapse into a single iframe write at the end
 * of the quiet period, with the most-recently-requested page winning.
 *
 * Why: setting `iframe.src` triggers a navigation in Chrome/Safari even
 * when only the fragment differs, so a rapid j/j/j press would otherwise
 * cause three sequential PDF re-renders + flashes. 250ms is fast enough
 * that a single deliberate press still feels instant, but slow enough
 * that "scroll through 10 pages" only writes once.
 */
export function createDebouncedPdfIframeSync(
  doc: DocumentLike,
  delayMs: number,
  timers: DebounceTimers = { setTimeout, clearTimeout },
): (page: number) => void {
  let pending: number | null = null;
  let timerId: number | null = null;
  return function sync(page: number): void {
    pending = page;
    if (timerId != null) timers.clearTimeout(timerId);
    timerId = timers.setTimeout(() => {
      timerId = null;
      const target = pending;
      pending = null;
      if (target != null) syncPdfIframeToPage(doc, target);
    }, delayMs);
  };
}
