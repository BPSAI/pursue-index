import { useEffect, useMemo, useReducer, useRef } from "preact/hooks";
import {
  reformatOcrText,
  pdfPageHref,
  clampPageIndex,
  readPageFromHash,
} from "./reader-format.ts";
import { createDebouncedPdfIframeSync } from "./pdf-iframe-sync.ts";
import { requiresUiNotice } from "./cleaned-pages.ts";

export interface ReaderPage {
  page: number;
  text: string;
  /**
   * When set, this page's cleanup pass did not produce usable cleaned
   * text. Codex P1 follow-up: the row is preserved in the cleaned
   * mirror for page-N alignment with the raw mirror; this flag tells
   * the renderer to surface the appropriate notice instead of an
   * empty article.
   *   - `"empty_input"`       → falls through to the existing
   *                             "[BLANK] No text extracted" path.
   *   - `"length_divergence"` → "[CLEANUP UNAVAILABLE]" with a
   *                             one-click switch to Raw mode.
   *   - `"content_filter"`    → "[CLEANUP UNAVAILABLE — content
   *                             filter]" with a one-click switch to
   *                             Raw mode. Honest but not alarming;
   *                             the reader knows what it means.
   * Raw mode does not set this field; rendering stays unchanged.
   */
  cleanupSkipped?: string;
}

interface Props {
  pages: ReaderPage[];
  /** Initial 1-indexed page from a #page-N hash, if present. */
  initialPage: number | null;
  /** Source PDF URL, used for the per-page "Read on war.gov" deep-link. */
  assetUrl?: string | null;
  /** Callback to switch back to raw mode (the toggle lives in the parent). */
  onSwitchToRaw: () => void;
}

/**
 * Reader-mode view of a card's OCR transcript.
 *
 * Renders one page at a time as prose (paragraph-reflowed; no monospace,
 * no `<pre>`), with prev/next navigation, a page counter, j/k keyboard
 * bindings, and a deep-link to the same page in the source PDF.
 *
 * The text reformat is one-shot (memoized on the active page only) — we
 * never re-flow on keystroke.
 */
export default function CardReaderView({
  pages,
  initialPage,
  assetUrl,
  onSwitchToRaw,
}: Props) {
  const total = pages.length;

  // Refs for everything that event handlers + the navigateTo callback
  // need to read live. The useReducer-based fix shipped earlier (commit
  // 6d41ac6) failed to clear the pagination regression — even with a
  // stable dispatch + ref-bound clamping, clicks beyond the first
  // continued to no-op on prod. The second-pass fix here removes the
  // dispatch path from the click hot-path entirely: handlers read the
  // current page from a ref, compute the target page directly, dispatch
  // an explicit `set` action (bypassing reducer state reads), and call
  // history.replaceState + iframe sync INLINE in the same call so
  // there's no deferred useEffect to race against.
  const totalRef = useRef(total);
  totalRef.current = total;

  // A debounced iframe-sync handle, lazily built once per mount. Why
  // debounce: setting `iframe.src` is a navigation in Chrome/WebKit even
  // when only the fragment changes — j/j/j would otherwise trigger three
  // PDF re-fetches + flashes. 250ms collapses bursts into a single write
  // (nayru P1 #1).
  const syncIframeRef = useRef<((page: number) => void) | null>(null);

  type Action = { type: "set"; page: number };
  const [activePage, dispatch] = useReducer<number, Action>(
    (state, action) => {
      if (action.type === "set") {
        return clampPageIndex(action.page, totalRef.current);
      }
      return state;
    },
    clampPageIndex(initialPage ?? 1, total),
  );

  // Track the live activePage in a ref so click/key handlers can compute
  // the next page without depending on closure freshness.
  const activePageRef = useRef(activePage);
  activePageRef.current = activePage;

  // The single navigation primitive used by buttons + keyboard. Reads
  // both totalRef and activePageRef so it can never race against a stale
  // closure. Dispatches an explicit `set` action (target page number),
  // then performs hash + iframe sync inline so the URL and PDF jump
  // in lock-step with the rendered page — no deferred useEffect, no
  // race window.
  const navigateTo = (next: number): void => {
    const target = clampPageIndex(next, totalRef.current);
    if (target === activePageRef.current) return;
    dispatch({ type: "set", page: target });
    if (typeof window === "undefined") return;
    const hash = `#page-${target}`;
    if (window.location.hash !== hash) {
      history.replaceState(null, "", hash);
    }
    if (!syncIframeRef.current) {
      syncIframeRef.current = createDebouncedPdfIframeSync(document, 250);
    }
    syncIframeRef.current(target);
  };

  // Initial-mount hash + iframe sync. Runs ONCE after mount so a deep
  // link (#page-N) lands the PDF iframe on the right page on first
  // paint. After that, navigateTo handles every transition inline.
  useEffect(() => {
    if (typeof window === "undefined" || total < 1) return;
    const target = `#page-${activePageRef.current}`;
    if (window.location.hash !== target) {
      history.replaceState(null, "", target);
    }
    if (!syncIframeRef.current) {
      syncIframeRef.current = createDebouncedPdfIframeSync(document, 250);
    }
    syncIframeRef.current(activePageRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Honor #page-N hash changes from outside (e.g. user paste).
  useEffect(() => {
    if (typeof window === "undefined") return;
    function onHashChange() {
      const fromHash = readPageFromHash(window.location.hash);
      if (fromHash != null) navigateTo(fromHash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // j/k + arrow-key bindings. Skip when focus is in an input/textarea so
  // we don't hijack typing. Vanilla DOM events; no hotkey library.
  useEffect(() => {
    if (typeof window === "undefined") return;
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || t?.isContentEditable) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        navigateTo(activePageRef.current + 1);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        navigateTo(activePageRef.current - 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = pages[activePage - 1];
  const paragraphs = useMemo(
    () => (current ? reformatOcrText(current.text) : []),
    [current],
  );
  const pdfHref = pdfPageHref(assetUrl, activePage);
  const showNav = total > 1;

  if (!current) {
    return null;
  }

  return (
    <div class="space-y-4">
      <div class="flex items-center justify-between gap-3 text-[11px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-dim)]">
        <span>
          <span class="text-[color:var(--color-signal-green)]">▸</span>{" "}
          Reader view — formatted from OCR.{" "}
          <button
            type="button"
            onClick={onSwitchToRaw}
            class="underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-signal-cyan)]"
          >
            Raw transcript →
          </button>
        </span>
      </div>

      <article
        data-pi-reader-page={current.page}
        class="prose prose-invert max-w-[65ch] mx-auto text-[color:var(--color-text)]"
        style="line-height: 1.7; font-family: var(--font-sans);"
      >
        {paragraphs.length > 0 ? (
          paragraphs.map((p, i) => (
            <p key={i} class="text-[15px] leading-[1.7] mb-4 text-[color:var(--color-text)]">
              {p}
            </p>
          ))
        ) : requiresUiNotice(current.cleanupSkipped) ? (
          <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
            <span class="text-[color:var(--color-signal-amber)]">
              {current.cleanupSkipped === "content_filter"
                ? "[CLEANUP UNAVAILABLE — content filter]"
                : "[CLEANUP UNAVAILABLE]"}
            </span>
            <span class="ml-2">
              Cleanup unavailable for this page —{" "}
              <button
                type="button"
                onClick={onSwitchToRaw}
                class="underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-signal-cyan)]"
              >
                view Raw mode
              </button>
              .
            </span>
          </p>
        ) : (
          <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
            <span class="text-[color:var(--color-signal-amber)]">[BLANK]</span>
            <span class="ml-2">No text extracted from this page.</span>
          </p>
        )}
      </article>

      <div class="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[color:var(--color-border)]">
        {showNav ? (
          <div class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.15em]">
            <button
              type="button"
              onClick={() => navigateTo(activePageRef.current - 1)}
              disabled={activePage <= 1}
              aria-label="Previous page"
              class="px-3 py-1.5 border border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-cyan)] hover:border-[color:var(--color-signal-cyan)] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-[color:var(--color-text-dim)] disabled:hover:border-[color:var(--color-border)]"
            >
              ← Prev <span class="text-[color:var(--color-text-faint)] ml-1 normal-case tracking-normal">k</span>
            </button>
            <span class="text-[color:var(--color-text-dim)]">
              Page <span class="text-[color:var(--color-signal-cyan)]">{activePage}</span>{" "}
              <span class="text-[color:var(--color-text-faint)]">of</span>{" "}
              <span class="text-[color:var(--color-text-bright)]">{total}</span>
            </span>
            <button
              type="button"
              onClick={() => navigateTo(activePageRef.current + 1)}
              disabled={activePage >= total}
              aria-label="Next page"
              class="px-3 py-1.5 border border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-cyan)] hover:border-[color:var(--color-signal-cyan)] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-[color:var(--color-text-dim)] disabled:hover:border-[color:var(--color-border)]"
            >
              Next → <span class="text-[color:var(--color-text-faint)] ml-1 normal-case tracking-normal">j</span>
            </button>
          </div>
        ) : (
          <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
            Single page
          </div>
        )}
        {pdfHref && (
          <a
            href={pdfHref}
            target="_blank"
            rel="noreferrer"
            class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-text-bright)]"
          >
            Read on war.gov →
          </a>
        )}
      </div>
    </div>
  );
}
