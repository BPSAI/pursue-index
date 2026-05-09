import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import MiniSearch from "minisearch";
import {
  buildHighlightRegex,
  buildSnippet,
  splitWithRegex,
  tokenize,
} from "./highlight";

interface PageDoc {
  id: string; // `${card_id}-p${page}`
  card_id: string;
  page: number;
  title: string;
  text: string;
}

interface Props {
  base: string;
}

type Status = "loading" | "missing" | "ready" | "error";

export default function SearchIsland({ base }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [docs, setDocs] = useState<PageDoc[]>([]);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

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
      .then((d) => {
        if (d) {
          setDocs(d);
          setStatus("ready");
        }
      })
      .catch((err) => {
        console.error(err);
        setStatus("error");
      });
  }, [base]);

  // Keyboard niceties: `/` focuses input from anywhere; `esc` clears.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !isTypingTarget(e.target)) {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      } else if (e.key === "Escape" && document.activeElement === inputRef.current) {
        setQuery("");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const search = useMemo(() => {
    if (status !== "ready" || docs.length === 0) return null;
    const ms = new MiniSearch<PageDoc>({
      fields: ["title", "text"],
      storeFields: ["card_id", "page", "title"],
      idField: "id",
      searchOptions: {
        boost: { title: 2 },
        prefix: true,
        fuzzy: 0.2,
      },
    });
    ms.addAll(docs);
    return ms;
  }, [status, docs]);

  const results = useMemo(() => {
    if (!search || !query.trim()) return [];
    return search.search(query, { combineWith: "AND" }).slice(0, 50);
  }, [search, query]);

  // Build a docs lookup so we can retrieve the full page text for snippet
  // extraction without bloating MiniSearch's storeFields.
  const docsById = useMemo(() => {
    const m = new Map<string, PageDoc>();
    for (const d of docs) m.set(d.id, d);
    return m;
  }, [docs]);

  // Highlight regex covers MiniSearch's matched terms (handles fuzzy/prefix
  // expansions) plus the raw query tokens, so a query like "alien craft"
  // marks both whole tokens even when MiniSearch matched only one stem.
  const queryTerms = useMemo(() => tokenize(query), [query]);
  const queryRegex = useMemo(
    () => buildHighlightRegex(queryTerms),
    [queryTerms],
  );

  if (status === "loading") {
    return (
      <div class="space-y-3">
        <div class="pi-sweep h-9"></div>
        <p class="pi-loading text-xs">DECLASSIFYING<span class="pi-caret"></span></p>
      </div>
    );
  }

  if (status === "missing") {
    return (
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-5 font-mono text-sm text-[color:var(--color-text)] pi-bracket relative scanlines-soft">
        <p class="text-[color:var(--color-signal-amber)] uppercase tracking-[0.18em] text-xs mb-2">
          [OCR PENDING]
        </p>
        <p>
          The Surya pass hasn't completed (or the next deploy hasn't shipped
          the index). Once published as
          <code class="mx-1 text-[color:var(--color-signal-cyan)]">/data/pages.json</code>
          this surface activates automatically.
        </p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-red)]">
        [ERR] Failed to load search index.
      </p>
    );
  }

  return (
    <div class="space-y-4">
      <div>
        <div class="relative">
          <input
            ref={inputRef}
            type="search"
            value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
            placeholder="search across all OCR'd pages…"
            class="w-full pr-16"
            autofocus
          />
          <kbd class="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[color:var(--color-text-faint)] border border-[color:var(--color-border)] px-1.5 py-0.5 rounded-sm pointer-events-none">
            /
          </kbd>
        </div>
        <p class="mt-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-green)]">{docs.length.toLocaleString()}</span>
          <span class="mx-1 text-[color:var(--color-text-faint)]">·</span>
          PAGES INDEXED
          <span class="mx-2 text-[color:var(--color-text-faint)]">|</span>
          <span class="text-[color:var(--color-text-faint)]">/ FOCUS · ESC CLEAR</span>
        </p>
      </div>
      {query.trim() && (
        <div class="text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] border-b border-[color:var(--color-border)] pb-1">
          <span class="text-[color:var(--color-signal-green)]">{results.length}</span> MATCH{results.length === 1 ? "" : "ES"}
          {results.length === 50 && <span class="text-[color:var(--color-signal-amber)] ml-2">(CAPPED)</span>}
        </div>
      )}
      <ul class="space-y-1.5">
        {results.map((r) => {
          const doc = docsById.get(r.id);
          // MiniSearch's `match` map includes the actual terms it matched
          // after fuzzy/prefix expansion (e.g. "aliens" for query "alien").
          // Build a regex covering both raw query terms and matched terms so
          // snippet highlighting reflects what actually scored.
          const matchedTerms = r.match ? Object.keys(r.match) : [];
          const allTerms = Array.from(new Set([...queryTerms, ...matchedTerms]));
          const snipRegex = buildHighlightRegex(allTerms);
          const snippet = doc?.text
            ? buildSnippet(doc.text, snipRegex, 140)
            : "";
          const linkQuery = encodeURIComponent(query.trim());
          const href = `${base}/card/${r.card_id}?q=${linkQuery}#page-${r.page}`;
          return (
            <li class="border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] hover:border-[color:var(--color-signal-green)]/50 transition-colors">
              <a href={href} class="block p-3 space-y-1.5">
                <div class="text-[10px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-faint)]">
                  <span class="text-[color:var(--color-signal-cyan)]">P{r.page}</span>
                  <span class="mx-2">·</span>
                  <span>SCORE {r.score.toFixed(2)}</span>
                  <span class="mx-2">·</span>
                  <span>{r.card_id.slice(0, 8)}</span>
                </div>
                <div class="text-sm text-[color:var(--color-text-bright)] line-clamp-2">
                  {r.title}
                </div>
                {snippet && (
                  <p class="font-mono text-[12px] leading-relaxed text-[color:var(--color-text-dim)] line-clamp-3">
                    {splitWithRegex(snippet, snipRegex).map((seg) =>
                      seg.kind === "match" ? (
                        <mark class="pi-mark">{seg.value}</mark>
                      ) : (
                        <span>{seg.value}</span>
                      ),
                    )}
                  </p>
                )}
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  const tag = t.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (t.isContentEditable) return true;
  return false;
}
