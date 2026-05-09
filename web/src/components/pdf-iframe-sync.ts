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
 *   Setting `iframe.src` to "<same-base>#page=N" updates the fragment
 *   without triggering a full reload in modern browsers (the base URL
 *   is unchanged). `contentWindow.location.hash` is blocked across
 *   origins (war.gov in our case), so it would throw. `src` is the
 *   only reliable cross-origin path.
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
 * when the iframe should not be touched (non-PDF asset, missing src, or
 * the src is already on the right page).
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
  if (assetType && assetType !== "PDF") return null;
  if (!Number.isInteger(page) || page < 1) return null;
  const base = current.split("#")[0];
  const target = `${base}#page=${page}`;
  if (current === target) return null;
  return target;
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
