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
 *   - the user is in raw mode (CardReaderView is not rendered, so its
 *     hashchange listener isn't installed — only this one fires).
 *
 * On the layered hashchange design (nayru P1 #4): when reader mode is
 * active, BOTH this listener AND CardReaderView's listener fire on the
 * same event. The second is a no-op (the `current === target` guard in
 * `nextIframeSrc` prevents a duplicate write). Keeping both is intentional
 * — removing this one would regress the raw-mode case where CardReaderView
 * is unmounted.
 *
 * Kept tiny on purpose: no framework, no state, just DOM lookups.
 */
import {
  readPageFromHash,
  readPageFromQuery,
  promotedCardUrl,
} from "../components/reader-format.ts";
import { syncPdfIframeToPage } from "../components/pdf-iframe-sync.ts";

function resolveActivePage(): number | null {
  const fromHash = readPageFromHash(window.location.hash);
  if (fromHash != null) return fromHash;
  return readPageFromQuery(window.location.search);
}

/**
 * Normalize `?page=N` into the canonical `#page-N` form, dropping the
 * redundant query param so a copy-pasted URL stays clean. Pure logic
 * lives in `promotedCardUrl`; this thin wrapper just talks to history.
 *
 * `replaceState` (never `pushState`) — this is a normalization, not
 * navigation. Don't trap the back button on a no-op rewrite.
 */
function promoteQueryToHash(): void {
  const next = promotedCardUrl(
    window.location.pathname,
    window.location.search,
    window.location.hash,
  );
  if (next == null) return;
  history.replaceState(null, "", next);
}

function syncFromUrl(): void {
  const page = resolveActivePage();
  if (page == null) return;
  syncPdfIframeToPage(document, page);
}

promoteQueryToHash();
syncFromUrl();
window.addEventListener("hashchange", syncFromUrl);
