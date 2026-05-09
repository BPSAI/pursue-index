/**
 * Page-level bootstrap that runs once on `/card/<id>` to keep the
 * embedded PDF iframe in sync with whichever page anchor (hash or
 * query) the URL carries on first load, and on every subsequent
 * `hashchange` triggered by the user (paste, browser-history nav, etc.).
 *
 * The reader-mode component (CardReaderView) does its own sync from
 * within Preact — that handles j/k and the prev/next buttons. This
 * script handles everything outside the island:
 *   - first paint after a citation chip lands at /card/<id>#page-7
 *   - first paint after an external link uses /card/<id>?page=7
 *   - the user pastes a different #page-N into the address bar
 *
 * Kept tiny on purpose: no framework, no state, just DOM lookups.
 */
import { readPageFromHash, readPageFromQuery } from "../components/reader-format.ts";
import { syncPdfIframeToPage } from "../components/pdf-iframe-sync.ts";

function resolveActivePage(): number | null {
  const fromHash = readPageFromHash(window.location.hash);
  if (fromHash != null) return fromHash;
  return readPageFromQuery(window.location.search);
}

/**
 * If the URL only has `?page=N` (no hash), promote it to `#page-N` so
 * the reader-mode component (which only reads the hash on mount) lands
 * on the right page. Use replaceState — we don't want a back-button
 * trap on a no-op normalization.
 */
function promoteQueryToHash(): void {
  if (window.location.hash) return;
  const fromQuery = readPageFromQuery(window.location.search);
  if (fromQuery == null) return;
  history.replaceState(null, "", `${window.location.pathname}${window.location.search}#page-${fromQuery}`);
}

function syncFromUrl(): void {
  const page = resolveActivePage();
  if (page == null) return;
  syncPdfIframeToPage(document, page);
}

promoteQueryToHash();
syncFromUrl();
window.addEventListener("hashchange", syncFromUrl);
