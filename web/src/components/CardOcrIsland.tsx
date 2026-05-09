import { useEffect, useMemo, useState } from "preact/hooks";

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
}: {
  pageData: CardPage;
  expanded: boolean;
  onToggle: () => void;
}) {
  const conf = formatConfidence(pageData.confidence);
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
            <pre class="font-mono text-[12px] leading-relaxed text-[color:var(--color-text)] whitespace-pre-wrap break-words">
              {pageData.text}
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

export default function CardOcrIsland({ cardId, base, assetType }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [pages, setPages] = useState<CardPage[]>([]);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

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
        const hash = typeof window !== "undefined" ? window.location.hash : "";
        const match = hash.match(/^#page-(\d+)$/);
        if (match) {
          const n = Number(match[1]);
          if (!Number.isNaN(n)) initial[n] = true;
        }
        setExpanded(initial);
        setStatus("ready");
      })
      .catch((err) => {
        console.error(err);
        setStatus("error");
      });
  }, [base, cardId]);

  // After the page list renders, scroll to #page-N if present.
  useEffect(() => {
    if (status !== "ready" || typeof window === "undefined") return;
    const hash = window.location.hash;
    const match = hash.match(/^#page-(\d+)$/);
    if (!match) return;
    const el = document.getElementById(`page-${match[1]}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [status, pages]);

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
      </div>
      <div class="space-y-2">
        {pages.map((p) => (
          <PageBlock
            key={p.page}
            pageData={p}
            expanded={!!expanded[p.page]}
            onToggle={() => toggle(p.page)}
          />
        ))}
      </div>
    </div>
  );
}
