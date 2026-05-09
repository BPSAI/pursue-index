import { useEffect, useMemo, useState } from "preact/hooks";
import {
  reformatOcrText,
  pdfPageHref,
  clampPageIndex,
  readPageFromHash,
} from "./reader-format.ts";

export interface ReaderPage {
  page: number;
  text: string;
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
  const [activePage, setActivePage] = useState<number>(() =>
    clampPageIndex(initialPage ?? 1, total),
  );

  // Sync the URL hash so deep-links remain copy-pasteable as the user
  // navigates. Replace (not push) — page-by-page paging shouldn't bloat
  // browser history.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (total < 1) return;
    const target = `#page-${activePage}`;
    if (window.location.hash !== target) {
      history.replaceState(null, "", target);
    }
  }, [activePage, total]);

  // Honor #page-N hash changes from outside (e.g. user paste).
  useEffect(() => {
    if (typeof window === "undefined") return;
    function onHashChange() {
      const fromHash = readPageFromHash(window.location.hash);
      if (fromHash != null) setActivePage(clampPageIndex(fromHash, total));
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [total]);

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
        setActivePage((p) => clampPageIndex(p + 1, total));
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setActivePage((p) => clampPageIndex(p - 1, total));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total]);

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
              onClick={() =>
                setActivePage((p) => clampPageIndex(p - 1, total))
              }
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
              onClick={() =>
                setActivePage((p) => clampPageIndex(p + 1, total))
              }
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
