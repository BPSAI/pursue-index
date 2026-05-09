import { useEffect, useMemo, useState } from "preact/hooks";
import {
  buildHighlightRegex,
  splitWithRegex,
  tokenize,
} from "./highlight";
import CardReaderView from "./CardReaderView.tsx";
import {
  loadReaderMode,
  readPageFromLocation,
  saveReaderMode,
  type ReaderMode,
} from "./reader-format.ts";

interface PageDoc {
  id: string;
  card_id: string;
  page: number;
  title: string;
  text: string;
  confidence?: number;
  engine?: string;
}

interface Props {
  cardId: string;
  base: string;
  /**
   * Asset type of the parent card. Used to tailor the empty-state copy
   * for IMG / VID cards that legitimately have no OCR pages.
   */
  assetType?: string;
  /**
   * Source PDF URL (war.gov) so reader-mode can deep-link "Read on
   * war.gov →" to the same page in the official viewer.
   */
  assetUrl?: string | null;
}

type Status = "loading" | "missing" | "ready" | "error";

interface CardPage {
  page: number;
  text: string;
  confidence: number;
  engine: string;
  anchorId: string;
}

function normalizePages(rows: PageDoc[], cardId: string): CardPage[] {
  const filtered = rows.filter((r) => r.card_id === cardId);
  filtered.sort((a, b) => a.page - b.page);
  return filtered.map((r) => ({
    page: r.page,
    text: r.text ?? "",
    confidence: typeof r.confidence === "number" ? r.confidence : 0,
    engine: r.engine ?? "tesseract",
    anchorId: `page-${r.page}`,
  }));
}

function formatConfidence(c: number): string {
  // confidence may be 0–1 (Tesseract per-page mean) or 0–100; normalize.
  if (!Number.isFinite(c) || c <= 0) return "—";
  const pct = c <= 1 ? c * 100 : c;
  return `${Math.round(pct)}%`;
}

function PageBlock({
  pageData,
  expanded,
  onToggle,
  highlightRegex,
  isActiveHighlightPage,
}: {
  pageData: CardPage;
  expanded: boolean;
  onToggle: () => void;
  highlightRegex: RegExp | null;
  /** True for the page that should carry data-pi-active so we can scroll to
   *  its first <mark>. Only one page is "active" at a time. */
  isActiveHighlightPage: boolean;
}) {
  const conf = formatConfidence(pageData.confidence);
  const segments = expanded
    ? splitWithRegex(pageData.text, highlightRegex)
    : [];
  let firstMatchSeen = false;
  return (
    <section
      id={pageData.anchorId}
      class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 scroll-mt-20"
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        class="w-full flex items-center gap-3 px-3 py-2 text-left font-mono text-[11px] uppercase tracking-[0.18em] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)] hover:bg-[color:var(--color-bg-elevated)] transition-colors"
      >
        <span class="text-[color:var(--color-signal-green)]">
          {expanded ? "▾" : "▸"}
        </span>
        <span class="text-[color:var(--color-signal-cyan)]">PAGE {pageData.page}</span>
        <span class="text-[color:var(--color-text-faint)]">·</span>
        <span>{conf}</span>
        <span class="text-[color:var(--color-text-faint)]">·</span>
        <span>{pageData.engine}</span>
      </button>
      {expanded && (
        <div class="border-t border-[color:var(--color-border)] px-4 py-3">
          {pageData.text.trim() ? (
            <pre
              data-pi-page={pageData.page}
              class="font-mono text-[12px] leading-relaxed text-[color:var(--color-text)] whitespace-pre-wrap break-words"
            >
              {segments.map((seg) => {
                if (seg.kind === "match") {
                  // Mark only the very first hit on the active page as the
                  // scroll-target — that's the "where do I start" anchor.
                  const isFirst = isActiveHighlightPage && !firstMatchSeen;
                  firstMatchSeen = true;
                  return (
                    <mark
                      class="pi-mark"
                      data-pi-first-match={isFirst ? "true" : "false"}
                    >
                      {seg.value}
                    </mark>
                  );
                }
                return <span>{seg.value}</span>;
              })}
            </pre>
          ) : (
            <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
              <span class="text-[color:var(--color-signal-amber)]">[BLANK]</span>
              <span class="ml-2">No text extracted from this page.</span>
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function emptyStateCopy(assetType?: string): string {
  if (assetType === "IMG") {
    return "No OCR — this is an IMG card; see the source asset above.";
  }
  if (assetType === "VID") {
    return "No OCR — this is a VID card; see the source asset above.";
  }
  return "No OCR pages were extracted for this card. The source asset above is the canonical reference.";
}

/**
 * Read the `q` URL param (set by SearchIsland's result links) and produce a
 * highlight regex covering every token in it. Returns null when there's no
 * query (so the OCR text renders unchanged).
 */
function readQueryRegex(): { regex: RegExp | null; raw: string } {
  if (typeof window === "undefined") return { regex: null, raw: "" };
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("q") ?? "";
  return { regex: buildHighlightRegex(tokenize(raw)), raw };
}

function activePageFromUrl(): number | null {
  if (typeof window === "undefined") return null;
  // Hash wins over query (see readPageFromLocation contract). The page-level
  // bootstrap script normalizes `?page=N` → `#page-N` before this island
  // hydrates, so by the time we read the URL the hash should already be
  // canonical — but checking both keeps us robust to script-load ordering.
  return readPageFromLocation(window.location.hash, window.location.search);
}

export default function CardOcrIsland({ cardId, base, assetType, assetUrl }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [pages, setPages] = useState<CardPage[]>([]);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  // Highlight state captured once on mount — query is sticky to the URL.
  const [highlight] = useState(() => readQueryRegex());
  const [activePage] = useState<number | null>(() => activePageFromUrl());
  // Reader/raw mode preference. Default "raw" preserves backward-compat
  // for existing visitors; new visitors discover Reader via the toggle.
  const [mode, setMode] = useState<ReaderMode>(() =>
    typeof window === "undefined" ? "raw" : loadReaderMode(window.localStorage),
  );
  const setModePersisted = (next: ReaderMode) => {
    setMode(next);
    if (typeof window !== "undefined") {
      saveReaderMode(window.localStorage, next);
    }
  };

  useEffect(() => {
    const url = `${base}/data/pages.json`;
    fetch(url)
      .then((r) => {
        if (r.status === 404) {
          setStatus("missing");
          return null;
        }
        if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
        return r.json() as Promise<PageDoc[]>;
      })
      .then((data) => {
        if (!data) return;
        const normalized = normalizePages(data, cardId);
        setPages(normalized);
        // First page expanded by default; honor #page-N hash on mount.
        const initial: Record<number, boolean> = {};
        if (normalized.length > 0) initial[normalized[0].page] = true;
        if (activePage != null) initial[activePage] = true;
        setExpanded(initial);
        setStatus("ready");
      })
      .catch((err) => {
        console.error(err);
        setStatus("error");
      });
  }, [base, cardId, activePage]);

  // After the page list renders, scroll to the first match on the anchored
  // page when ?q= is present; otherwise fall back to scrolling the page top.
  useEffect(() => {
    if (status !== "ready" || typeof window === "undefined") return;
    if (activePage == null) return;
    // Defer to next frame so the DOM has the freshly-rendered <mark> nodes.
    const raf = requestAnimationFrame(() => {
      if (highlight.regex) {
        const firstMark = document.querySelector<HTMLElement>(
          `[data-pi-first-match="true"]`,
        );
        if (firstMark) {
          firstMark.setAttribute("data-active", "true");
          firstMark.scrollIntoView({ behavior: "smooth", block: "center" });
          return;
        }
      }
      const el = document.getElementById(`page-${activePage}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => cancelAnimationFrame(raf);
  }, [status, pages, activePage, highlight]);

  const totalChars = useMemo(
    () => pages.reduce((acc, p) => acc + p.text.length, 0),
    [pages],
  );

  if (status === "loading") {
    return (
      <div class="space-y-3">
        <div class="pi-sweep h-9"></div>
        <p class="pi-loading text-xs">
          DECLASSIFYING<span class="pi-caret"></span>
        </p>
      </div>
    );
  }

  if (status === "missing") {
    return (
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-4 font-mono text-xs text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-amber)]">[OCR PENDING]</span>
        <span class="block mt-1">
          The page index hasn't been published yet. Once it ships at{" "}
          <code class="text-[color:var(--color-signal-cyan)]">/data/pages.json</code>{" "}
          this surface activates automatically.
        </span>
      </div>
    );
  }

  if (status === "error") {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-red)]">
        [ERR] Failed to load OCR text.
      </p>
    );
  }

  if (pages.length === 0) {
    return (
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-4 font-mono text-xs text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-amber)]">[NO OCR]</span>
        <span class="block mt-1">{emptyStateCopy(assetType)}</span>
      </div>
    );
  }

  const toggle = (page: number) =>
    setExpanded((prev) => ({ ...prev, [page]: !prev[page] }));

  return (
    <div class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
          <span>
            <span class="text-[color:var(--color-signal-green)]">{pages.length}</span>{" "}
            PAGE{pages.length === 1 ? "" : "S"}
          </span>
          <span class="text-[color:var(--color-text-faint)]">·</span>
          <span>
            <span class="text-[color:var(--color-text-bright)]">
              {totalChars.toLocaleString()}
            </span>{" "}
            CHARS
          </span>
          {highlight.raw && (
            <>
              <span class="text-[color:var(--color-text-faint)]">·</span>
              <span class="normal-case tracking-normal">
                <span class="text-[color:var(--color-text-faint)] uppercase tracking-[0.15em]">Q</span>
                <mark class="pi-mark ml-2 font-mono">{highlight.raw}</mark>
              </span>
            </>
          )}
        </div>
        <div
          role="group"
          aria-label="OCR display mode"
          class="inline-flex font-mono text-[11px] uppercase tracking-[0.15em] border border-[color:var(--color-border)]"
        >
          <button
            type="button"
            aria-pressed={mode === "raw"}
            onClick={() => setModePersisted("raw")}
            class={`px-3 py-1.5 transition-colors ${
              mode === "raw"
                ? "bg-[color:var(--color-bg-elevated)] text-[color:var(--color-signal-cyan)]"
                : "text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
            }`}
          >
            Raw
          </button>
          <button
            type="button"
            aria-pressed={mode === "reader"}
            onClick={() => setModePersisted("reader")}
            class={`px-3 py-1.5 border-l border-[color:var(--color-border)] transition-colors ${
              mode === "reader"
                ? "bg-[color:var(--color-bg-elevated)] text-[color:var(--color-signal-cyan)]"
                : "text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
            }`}
          >
            Reader
          </button>
        </div>
      </div>
      {mode === "reader" ? (
        <CardReaderView
          pages={pages.map((p) => ({ page: p.page, text: p.text }))}
          initialPage={activePage}
          assetUrl={assetUrl}
          onSwitchToRaw={() => setModePersisted("raw")}
        />
      ) : (
        <div class="space-y-2">
          {pages.map((p) => (
            <PageBlock
              key={p.page}
              pageData={p}
              expanded={!!expanded[p.page]}
              onToggle={() => toggle(p.page)}
              highlightRegex={highlight.regex}
              isActiveHighlightPage={activePage === p.page}
            />
          ))}
        </div>
      )}
    </div>
  );
}
