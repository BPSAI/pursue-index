import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import MiniSearch from "minisearch";
import {
  buildHighlightRegex,
  buildSnippet,
  tokenize,
} from "./highlight";
import {
  buildSearchIndexOptions,
  hasMatchSegment,
  highlightSegments,
} from "./search-result-highlight.ts";
import SearchFilterRail from "./SearchFilterRail.tsx";
import {
  EMPTY_FILTERS,
  agencyCounts as buildAgencyCounts,
  cardMatchesFilters,
  filtersToQueryString,
  parseFiltersFromQuery,
  type SearchFilters,
} from "./search-filters.ts";
import {
  ActiveFilterBadge,
  EmptyResults,
  hasActiveFilters,
} from "./search-result-chrome.tsx";
import type { CardMetadata } from "../data/types.ts";

// URL keys this island owns — anything else (utm_*, fbclid, ref, gclid…)
// must survive the writer effect untouched. PR #5 review F1.
const OWNED_URL_KEYS = ["q", "agency", "from", "to", "redacted"] as const;

interface PageDoc {
  id: string; // `${card_id}-p${page}`
  card_id: string;
  page: number;
  title: string;
  text: string;
}

interface Props {
  base: string;
  /**
   * Optional clickable example queries shown beneath the input when empty.
   * Used by the homepage hero to advertise representative searches; the
   * `/search` route omits this and just shows the bare input.
   */
  examples?: readonly string[];
  /**
   * When supplied, renders the faceted filter rail (agency / date /
   * redacted) and applies filters to results. Cards are looked up by
   * `card_id` to scope search hits. Omitted on the homepage hero.
   */
  cards?: CardMetadata[];
  /** Whether to render the filter rail. Requires `cards` to be set. */
  enableFilters?: boolean;
}

type Status = "loading" | "missing" | "ready" | "error";

export default function SearchIsland({ base, examples, cards, enableFilters }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [docs, setDocs] = useState<PageDoc[]>([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  const inputRef = useRef<HTMLInputElement>(null);
  const filtersOn = !!(enableFilters && cards && cards.length > 0);

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

  // Hydrate query + filters from URL on mount. Gated on `filtersOn` so the
  // homepage hero (no filter rail) doesn't touch the URL at all — its
  // submit-on-Enter sends users to /search where the real hydrate happens.
  // The `useRef` flag prevents the writer effect below from running before
  // hydration completes (which would clobber a shared `?q=foo&agency=FBI`
  // link with the empty default state on first render).
  const hydrated = useRef(false);
  useEffect(() => {
    if (!filtersOn) {
      // Nothing to hydrate or sync; mark as "done" so the writer's
      // early-return continues to short-circuit even if filtersOn flips.
      hydrated.current = true;
      return;
    }
    const search = window.location.search;
    const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
    const q = params.get("q");
    if (q) setQuery(q);
    setFilters(parseFiltersFromQuery(search));
    hydrated.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // ^ Mount-only. We deliberately ignore later changes to `filtersOn`:
    //   the URL is the source of truth, and re-hydrating mid-session would
    //   undo any user edits made since mount.
  }, []);

  useEffect(() => {
    // Only the filter-enabled mount writes back to the URL — preserves the
    // homepage hero's behavior of being a pure submit-and-redirect input
    // (it doesn't own the location bar). PR #5 review F2.
    if (!filtersOn || !hydrated.current) return;
    // Seed from existing search params so we preserve any unrelated
    // analytics/referral params (utm_*, fbclid, ref, gclid…). We only
    // delete + re-set the keys this island owns. PR #5 review F1.
    const params = new URLSearchParams(window.location.search);
    for (const k of OWNED_URL_KEYS) params.delete(k);
    if (query.trim()) params.set("q", query.trim());
    const fqs = filtersToQueryString(filters);
    if (fqs) {
      for (const [k, v] of new URLSearchParams(fqs)) params.set(k, v);
    }
    const qs = params.toString();
    history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [query, filters, filtersOn]);

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
    // Options live in `search-result-highlight.ts` so the test suite can
    // construct an identical index; see that module for why fuzzy is off.
    const ms = new MiniSearch<PageDoc>(buildSearchIndexOptions<PageDoc>());
    ms.addAll(docs);
    return ms;
  }, [status, docs]);

  // card_id → CardMetadata, so we can apply the filter predicate to each
  // MiniSearch hit's parent card without an O(n) lookup per result.
  const cardsById = useMemo(() => {
    const m = new Map<string, CardMetadata>();
    if (cards) for (const c of cards) m.set(c.card_id, c);
    return m;
  }, [cards]);
  const agencies = useMemo(
    () => (cards ? Array.from(new Set(cards.map((c) => c.agency))).sort() : []),
    [cards],
  );
  const agencyCountMap = useMemo(
    () => buildAgencyCounts(cards ?? []),
    [cards],
  );

  // Track the *unsliced* total so the "(CAPPED)" badge only shows when we
  // actually truncated. With filters on, totalMatches reflects filtered
  // count (it'd be misleading to advertise pre-filter totals).
  const { results, totalMatches } = useMemo(() => {
    if (!search || !query.trim()) return { results: [], totalMatches: 0 };
    const all = search.search(query, { combineWith: "AND" });
    const scoped = filtersOn
      ? all.filter((r) => {
          const card = cardsById.get(r.card_id);
          return card ? cardMatchesFilters(card, filters) : false;
        })
      : all;
    return { results: scoped.slice(0, 50), totalMatches: scoped.length };
  }, [search, query, filtersOn, filters, cardsById]);

  // Build a docs lookup so we can retrieve the full page text for snippet
  // extraction without bloating MiniSearch's storeFields.
  const docsById = useMemo(() => {
    const m = new Map<string, PageDoc>();
    for (const d of docs) m.set(d.id, d);
    return m;
  }, [docs]);

  const queryTerms = useMemo(() => tokenize(query), [query]);
  const queryRegex = useMemo(
    () => buildHighlightRegex(queryTerms),
    [queryTerms],
  );

  if (status === "loading") {
    return (
      <div class="space-y-3" role="status">
        <div class="pi-sweep h-9" aria-hidden="true"></div>
        <p class="pi-loading text-xs">DECLASSIFYING<span class="pi-caret" aria-hidden="true"></span></p>
        <span class="sr-only">Loading search index, please wait</span>
      </div>
    );
  }

  if (status === "missing") {
    return (
      <div
        role="status"
        class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-5 font-mono text-sm text-[color:var(--color-text)] pi-bracket relative scanlines-soft"
      >
        <p class="text-[color:var(--color-signal-amber)] uppercase tracking-[0.18em] text-xs mb-2">
          <span class="sr-only">Status: </span>[OCR PENDING]
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
      <p
        role="alert"
        class="font-mono text-sm text-[color:var(--color-signal-red)]"
      >
        <span class="sr-only">Error: </span>[ERR] Failed to load search index.
      </p>
    );
  }

  const main = (
    <div class="space-y-4 min-w-0">
      <div>
        <div class="relative">
          <input
            ref={inputRef}
            type="search"
            value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
            placeholder={`search ${docs.length.toLocaleString()} OCR'd pages…`}
            class="w-full pr-16"
            aria-label="Search OCR'd pages across the PURSUE corpus"
            autofocus
          />
          <kbd class="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[color:var(--color-text-faint)] border border-[color:var(--color-border)] px-1.5 py-0.5 rounded-sm pointer-events-none">
            /
          </kbd>
        </div>
        <p class="mt-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-green)]">{docs.length.toLocaleString()}</span>
          <span aria-hidden="true" class="mx-1 text-[color:var(--color-text-faint)]">·</span>
          PAGES INDEXED
          <span aria-hidden="true" class="mx-2 text-[color:var(--color-text-faint)]">|</span>
          <span class="text-[color:var(--color-text-faint)]">/ FOCUS · ESC CLEAR</span>
        </p>
        {examples && examples.length > 0 && !query.trim() && (
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <span class="text-[10px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-faint)]">
              try:
            </span>
            {examples.map((ex) => (
              <button
                type="button"
                onClick={() => {
                  setQuery(ex);
                  inputRef.current?.focus();
                }}
                class="px-2 py-1 text-[11px] font-mono border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-signal-green)]/60 hover:text-[color:var(--color-signal-green)] transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
        )}
      </div>
      {filtersOn && <ActiveFilterBadge filters={filters} onClear={() => setFilters(EMPTY_FILTERS)} />}
      {/* aria-live so screen readers announce the new match count when
          the user types or changes filters; aria-atomic="true" so the
          whole sentence is re-spoken as a unit instead of just the
          changed digits. */}
      <div
        aria-live="polite"
        aria-atomic="true"
        class="text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]"
      >
        {query.trim() && (
          <div class="border-b border-[color:var(--color-border)] pb-1">
            <span class="text-[color:var(--color-signal-green)]">{totalMatches}</span> MATCH{totalMatches === 1 ? "" : "ES"}
            {totalMatches > 50 && <span class="text-[color:var(--color-signal-amber)] ml-2">(CAPPED)</span>}
          </div>
        )}
      </div>
      {query.trim() && totalMatches === 0 && (
        <EmptyResults filtersOn={filtersOn} hasActive={hasActiveFilters(filters)} onClear={() => setFilters(EMPTY_FILTERS)} />
      )}
      <ul class="space-y-1.5">
        {results.map((r) => {
          const doc = docsById.get(r.id);
          const matchedTerms = r.match ? Object.keys(r.match) : [];
          const allTerms = Array.from(new Set([...queryTerms, ...matchedTerms]));
          const snipRegex = buildHighlightRegex(allTerms);
          const snippet = doc?.text
            ? buildSnippet(doc.text, snipRegex, 140)
            : "";
          const titleSegments = highlightSegments(r.title, snipRegex);
          // Title-only hits would otherwise render an unhighlighted slice
          // of body text (buildSnippet falls back to head-of-text when it
          // can't find a match). Suppress the snippet block in that case
          // — the highlighted title already shows where the match lives.
          const snippetSegments = snippet
            ? highlightSegments(snippet, snipRegex)
            : [];
          // Boolean-coerce: `snippet` is a string and JSX would otherwise
          // render an empty `""` falsy-but-defined branch when `&&` short-
          // circuits on it. (nayru P1 on PR #29.)
          const showSnippet = Boolean(snippet) && hasMatchSegment(snippetSegments);
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
                  {titleSegments.map((seg, i) =>
                    seg.kind === "match" ? (
                      <mark key={i} class="pi-mark">{seg.value}</mark>
                    ) : (
                      <span key={i}>{seg.value}</span>
                    ),
                  )}
                </div>
                {showSnippet && (
                  <p class="font-mono text-[12px] leading-relaxed text-[color:var(--color-text-dim)] line-clamp-3">
                    {snippetSegments.map((seg, i) =>
                      seg.kind === "match" ? (
                        <mark key={i} class="pi-mark">{seg.value}</mark>
                      ) : (
                        <span key={i}>{seg.value}</span>
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

  if (!filtersOn) return main;

  return (
    <div class="grid grid-cols-1 md:grid-cols-[15rem_1fr] gap-4 md:gap-6">
      <SearchFilterRail
        filters={filters}
        setFilters={setFilters}
        agencies={agencies}
        agencyCounts={agencyCountMap}
      />
      {main}
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
