import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";
import { loadCardsSummary } from "./card-summary-loader";
import {
  DISCLOSURE_TONE,
  EMPTY_NOVELTY,
  corpusTag,
  disclosurePillLabel,
  loadNovelty,
  passesDisclosureFilter,
  type DisclosureFilter,
  type NoveltyState,
} from "./NoveltyFilter";

interface Props {
  /**
   * Card list. When omitted, CardExplorer fetches
   * `${base}/data/cards-summary.json` on hydration. Sprint 4b Theme F:
   * the homepage no longer passes this prop, dropping 440 KB of inline
   * HTML-encoded JSON from dist/index.html. Other callers (tests,
   * future server-rendered surfaces) can still pass cards directly.
   */
  cards?: CardMetadata[];
  base: string;
}

type SortKey = "title" | "release" | "incident" | "type";
type ViewMode = "cards" | "table";

const TYPE_TONE: Record<string, { bg: string; text: string; border: string; label: string }> = {
  PDF: {
    bg: "bg-[color:var(--color-signal-red)]/10",
    text: "text-[color:var(--color-signal-red)]",
    border: "border-[color:var(--color-signal-red)]/40",
    label: "PDF",
  },
  IMG: {
    bg: "bg-[color:var(--color-signal-green)]/10",
    text: "text-[color:var(--color-signal-green)]",
    border: "border-[color:var(--color-signal-green)]/40",
    label: "IMG",
  },
  VID: {
    bg: "bg-[color:var(--color-signal-violet)]/10",
    text: "text-[color:var(--color-signal-violet)]",
    border: "border-[color:var(--color-signal-violet)]/40",
    label: "VID",
  },
  // Sprint 4f: upstream relabeled the NASA Gemini 7 audio card from
  // VID → AUD in tranche f75e2f7. Audio is DVIDS-hosted like video;
  // a distinct badge keeps the filter UI honest.
  AUD: {
    bg: "bg-[color:var(--color-signal-amber)]/10",
    text: "text-[color:var(--color-signal-amber)]",
    border: "border-[color:var(--color-signal-amber)]/40",
    label: "AUD",
  },
};

function TypeBadge({ type }: { type: string }) {
  const tone = TYPE_TONE[type];
  if (!tone) return <span class="text-[10px] font-mono">{type}</span>;
  return (
    <span
      class={`text-[10px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 border ${tone.bg} ${tone.text} ${tone.border}`}
    >
      {tone.label}
    </span>
  );
}

export default function CardExplorer({ cards: cardsProp, base }: Props) {
  // Sprint 4b Theme F: when `cards` is omitted, fetch the slim summary
  // on hydration. `null` is the "fetch hasn't resolved yet" sentinel —
  // distinct from `[]` (resolved-but-empty) so the record counter can
  // hide the `0 / 0 RECORDS` flash that would otherwise render between
  // hydration and the first fetch completion. When `cards` is provided
  // (legacy callers, tests), we use it directly and skip the fetch.
  // Cache policy: 1h fresh + 24h stale-while-revalidate is applied by
  // worker/index.js::withCacheHeaders (the `/data/<file>.json` rule).
  // See `card-summary-loader.ts` for the fetch options.
  const [cards, setCards] = useState<CardMetadata[] | null>(
    cardsProp ?? null,
  );
  useEffect(() => {
    if (cardsProp !== undefined) return;
    let cancelled = false;
    loadCardsSummary(base).then((loaded) => {
      if (!cancelled) setCards(loaded);
    });
    return () => {
      cancelled = true;
    };
    // base is build-time stable; cardsProp is the SSR escape hatch.
  }, [base, cardsProp]);
  // Resolved view: empty array before first fetch resolves; the
  // counter below suppresses the "X / Y RECORDS" line until non-null.
  const resolvedCards = cards ?? [];

  const agencies = useMemo(
    () => Array.from(new Set(resolvedCards.map((c) => c.agency))).sort(),
    [resolvedCards],
  );

  const [query, setQuery] = useState("");
  const [agency, setAgency] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [disclosure, setDisclosure] = useState<DisclosureFilter>("");
  const [redactedOnly, setRedactedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("title");
  const [view, setView] = useState<ViewMode>("cards");
  const [novelty, setNovelty] = useState<NoveltyState>(EMPTY_NOVELTY);

  // Fetch novelty payload once on mount. Failure is silent — the filter
  // disables and pills don't render when `available` stays false.
  useEffect(() => {
    let cancelled = false;
    loadNovelty(base).then((n) => {
      if (!cancelled) setNovelty(n);
    });
    return () => {
      cancelled = true;
    };
  }, [base]);

  // Effect-ordering guard: the URL-sync effect must NOT run on the very
  // first render (state is still defaults), or it will overwrite the hash
  // before the hydrate effect captures it. So a shared `/#q=apollo` link
  // would lose its query. The ref flips true at the end of the hydrate
  // effect; the sync effect early-returns until then.
  const hydrated = useRef(false);

  // Hydrate from hash on mount.
  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    if (hash) {
      const params = new URLSearchParams(hash);
      if (params.get("q")) setQuery(params.get("q")!);
      if (params.get("agency")) setAgency(params.get("agency")!);
      if (params.get("type")) setType(params.get("type")!);
      if (params.get("redacted") === "1") setRedactedOnly(true);
      const d = params.get("disclosure");
      if (d === "novel" || d === "partial" || d === "previously-disclosed") {
        setDisclosure(d);
      }
      const s = params.get("sort");
      if (s === "release" || s === "incident" || s === "type") setSort(s);
      const v = params.get("view");
      if (v === "table" || v === "cards") setView(v);
    }
    hydrated.current = true;
  }, []);

  // Sync state to URL hash so links are shareable.
  useEffect(() => {
    if (!hydrated.current) return;
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (agency) params.set("agency", agency);
    if (type) params.set("type", type);
    if (redactedOnly) params.set("redacted", "1");
    if (disclosure) params.set("disclosure", disclosure);
    if (sort !== "title") params.set("sort", sort);
    if (view !== "cards") params.set("view", view);
    const next = params.toString();
    const url = next ? `#${next}` : window.location.pathname;
    history.replaceState(null, "", url);
  }, [query, agency, type, redactedOnly, disclosure, sort, view]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = resolvedCards.filter((c) => {
      if (agency && c.agency !== agency) return false;
      if (type && c.asset_type !== type) return false;
      if (redactedOnly && !c.redacted) return false;
      if (!passesDisclosureFilter(c.card_id, disclosure, novelty)) return false;
      if (q) {
        const hay =
          `${c.title} ${c.description ?? ""} ${c.incident_location ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    return list.sort((a, b) => {
      switch (sort) {
        case "release":
          return (a.release_date ?? "").localeCompare(b.release_date ?? "");
        case "incident":
          return (a.incident_date ?? "").localeCompare(b.incident_date ?? "");
        case "type":
          return a.asset_type.localeCompare(b.asset_type);
        default:
          return a.title.localeCompare(b.title);
      }
    });
  }, [resolvedCards, query, agency, type, redactedOnly, disclosure, novelty, sort]);

  return (
    <div class="space-y-6">
      <Filters
        query={query}
        setQuery={setQuery}
        agency={agency}
        setAgency={setAgency}
        type={type}
        setType={setType}
        redactedOnly={redactedOnly}
        setRedactedOnly={setRedactedOnly}
        disclosure={disclosure}
        setDisclosure={setDisclosure}
        disclosureAvailable={novelty.available}
        sort={sort}
        setSort={setSort}
        agencies={agencies}
      />

      <div class="flex items-center justify-between border-b border-[color:var(--color-border)] pb-2">
        {/* Suppress the `0 / 0 RECORDS` flash before the first fetch
            resolves. `cards === null` means "hydration ran but the
            fetch hasn't completed" — render an unobtrusive
            placeholder so the row keeps its height (CLS guard) but
            the misleading zero doesn't appear. nayru P1#4. */}
        <div class="text-[11px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-dim)]">
          {cards === null ? (
            <span class="text-[color:var(--color-text-faint)]">LOADING…</span>
          ) : (
            <>
              <span class="text-[color:var(--color-signal-green)]">{filtered.length}</span>
              <span class="mx-1 text-[color:var(--color-text-faint)]">/</span>
              {resolvedCards.length} RECORDS
            </>
          )}
        </div>
        <ViewToggle view={view} setView={setView} />
      </div>

      {view === "cards" ? (
        <CardGrid filtered={filtered} base={base} novelty={novelty} />
      ) : (
        <TableView filtered={filtered} base={base} />
      )}

      {/* [NO MATCH] only renders once the fetch resolves — otherwise
          it flashes during the brief pre-fetch window where
          `resolvedCards` is `[]` and `filtered.length === 0` looks
          like a user-facing "no results" state when it's actually a
          hydration state. nayru P1#4. */}
      {cards !== null && filtered.length === 0 && (
        <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-8 text-center font-mono text-sm text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-amber)]">[NO MATCH]</span>
          <span class="ml-2">loosen a filter or clear the query.</span>
        </div>
      )}
    </div>
  );
}

interface FiltersProps {
  query: string;
  setQuery: (v: string) => void;
  agency: string;
  setAgency: (v: string) => void;
  type: string;
  setType: (v: string) => void;
  redactedOnly: boolean;
  setRedactedOnly: (v: boolean) => void;
  disclosure: DisclosureFilter;
  setDisclosure: (v: DisclosureFilter) => void;
  disclosureAvailable: boolean;
  sort: SortKey;
  setSort: (v: SortKey) => void;
  agencies: string[];
}

function Filters(p: FiltersProps) {
  return (
    <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_auto_auto_auto_auto] lg:items-end">
      <div>
        <label class="block text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-text-faint)] mb-1.5">
          QUERY
        </label>
        <input
          type="search"
          value={p.query}
          onInput={(e) => p.setQuery((e.target as HTMLInputElement).value)}
          placeholder="title / description / location…"
          class="w-full"
        />
      </div>
      <Selector label="AGENCY" value={p.agency} onChange={p.setAgency} options={["", ...p.agencies]} />
      <Selector label="TYPE" value={p.type} onChange={p.setType} options={["", "PDF", "IMG", "VID", "AUD"]} />
      <Selector
        label="DISCLOSURE"
        value={p.disclosure}
        onChange={(v) => p.setDisclosure(v as DisclosureFilter)}
        options={["", "novel", "partial", "previously-disclosed"]}
        disabled={!p.disclosureAvailable}
        title={
          p.disclosureAvailable
            ? undefined
            : "novelty comparison not yet computed for this corpus"
        }
      />
      <Selector
        label="SORT"
        value={p.sort}
        onChange={(v) => p.setSort(v as SortKey)}
        options={["title", "release", "incident", "type"]}
      />
      <label class="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] lg:pb-2 cursor-pointer">
        <input
          type="checkbox"
          checked={p.redactedOnly}
          onChange={(e) => p.setRedactedOnly((e.target as HTMLInputElement).checked)}
          class="accent-[color:var(--color-signal-red)]"
        />
        REDACTED
      </label>
    </div>
  );
}

function ViewToggle({ view, setView }: { view: ViewMode; setView: (v: ViewMode) => void }) {
  const btn = (mode: ViewMode, label: string) => (
    <button
      type="button"
      onClick={() => setView(mode)}
      class={`px-3 py-1 text-[10px] font-mono uppercase tracking-[0.18em] border ${
        view === mode
          ? "bg-[color:var(--color-signal-green)]/15 border-[color:var(--color-signal-green)]/50 text-[color:var(--color-signal-green)]"
          : "bg-transparent border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div class="flex gap-px">
      {btn("cards", "CARDS")}
      {btn("table", "TABLE")}
    </div>
  );
}

function DisclosurePill({
  status,
  archiveId,
}: {
  status: keyof typeof DISCLOSURE_TONE;
  archiveId?: string;
}) {
  const tone = DISCLOSURE_TONE[status];
  if (!tone) return null;
  const label = disclosurePillLabel(status, archiveId);
  return (
    <span
      data-corpus={corpusTag(archiveId)}
      class={`inline-flex items-baseline gap-1 text-[9px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 border ${tone.bg} ${tone.fg} ${tone.border}`}
    >
      <span>{label.status}</span>
      <span class="text-[7px] tracking-[0.1em] opacity-70 normal-case">
        {label.qualifier}
      </span>
    </span>
  );
}

function CardGrid({
  filtered,
  base,
  novelty,
}: {
  filtered: CardMetadata[];
  base: string;
  novelty: NoveltyState;
}) {
  return (
    <ul class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {filtered.map((c) => (
        <li class="group border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] hover:border-[color:var(--color-signal-green)]/60 hover:bg-[color:var(--color-bg-raised)] transition-colors relative scanlines-soft">
          <a href={`${base}/card/${c.card_id}`} class="block p-4 space-y-2.5 relative z-10">
            <div class="flex items-center gap-2 flex-wrap">
              <TypeBadge type={c.asset_type} />
              <span class="text-[10px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
                {c.agency}
              </span>
              {c.redacted && (
                <span class="text-[10px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-signal-red)] font-semibold">
                  REDACTED
                </span>
              )}
              {novelty.available && novelty.cards[c.card_id] && (
                <DisclosurePill
                  status={novelty.cards[c.card_id].disclosure_status}
                  archiveId={novelty.archiveId}
                />
              )}
              <span class="ml-auto text-[10px] font-mono text-[color:var(--color-text-faint)]">
                {c.card_id.slice(0, 8)}
              </span>
            </div>
            <h3 class="text-sm font-medium leading-snug text-[color:var(--color-text-bright)] line-clamp-3 group-hover:text-[color:var(--color-signal-green)] transition-colors">
              {c.title}
            </h3>
            <div class="text-[11px] font-mono text-[color:var(--color-text-dim)] flex items-center gap-3 flex-wrap">
              {c.incident_date && <span>INC {c.incident_date}</span>}
              {c.incident_location && (
                <span class="truncate text-[color:var(--color-signal-cyan)]">
                  ▸ {c.incident_location}
                </span>
              )}
            </div>
            {c.description && (
              <p class="text-xs text-[color:var(--color-text)] line-clamp-3">{c.description}</p>
            )}
          </a>
        </li>
      ))}
    </ul>
  );
}

function TableView({ filtered, base }: { filtered: CardMetadata[]; base: string }) {
  return (
    <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 overflow-x-auto font-mono text-[12px]">
      <table class="w-full">
        <thead class="bg-[color:var(--color-bg-elevated)] border-b border-[color:var(--color-border)] text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-text-faint)]">
          <tr>
            <th class="text-left px-3 py-2 w-20">TYPE</th>
            <th class="text-left px-3 py-2 w-32">AGENCY</th>
            <th class="text-left px-3 py-2 w-24">INCIDENT</th>
            <th class="text-left px-3 py-2">TITLE</th>
            <th class="text-left px-3 py-2 w-40">LOCATION</th>
            <th class="text-left px-3 py-2 w-24">CARD_ID</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((c, i) => (
            <tr
              class={`border-b border-[color:var(--color-border)] hover:bg-[color:var(--color-bg-elevated)] ${
                i % 2 === 0 ? "bg-transparent" : "bg-[color:var(--color-bg)]/30"
              }`}
            >
              <td class="px-3 py-1.5"><TypeBadge type={c.asset_type} /></td>
              <td class="px-3 py-1.5 text-[color:var(--color-text-dim)]">{c.agency}</td>
              <td class="px-3 py-1.5 text-[color:var(--color-text-dim)]">
                {c.incident_date ?? <span class="text-[color:var(--color-text-faint)]">—</span>}
              </td>
              <td class="px-3 py-1.5 text-[color:var(--color-text-bright)] truncate max-w-md">
                <a href={`${base}/card/${c.card_id}`} class="hover:text-[color:var(--color-signal-green)]">
                  {c.redacted && <span class="text-[color:var(--color-signal-red)] mr-1">●</span>}
                  {c.title}
                </a>
              </td>
              <td class="px-3 py-1.5 text-[color:var(--color-signal-cyan)] truncate">
                {c.incident_location ?? <span class="text-[color:var(--color-text-faint)]">—</span>}
              </td>
              <td class="px-3 py-1.5 text-[color:var(--color-text-faint)]">{c.card_id.slice(0, 8)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Selector({
  label,
  value,
  onChange,
  options,
  disabled,
  title,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  disabled?: boolean;
  title?: string;
}) {
  // Wrapping <label> implicitly associates with the <select> inside it
  // (HTML spec: a labeled control is the first descendant labelable
  // element). Wrapping is preferred over for/id because it's robust to
  // the consumer rendering multiple Selectors without coordinating ids.
  return (
    <div title={title}>
      <label class="block">
        <span class="block text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-text-faint)] mb-1.5">
          {label}
          {disabled && (
            <span class="ml-1 text-[color:var(--color-text-faint)] normal-case tracking-normal">
              (n/a)
            </span>
          )}
        </span>
        <select
          value={value}
          disabled={disabled}
          onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
          class="w-full lg:w-auto disabled:opacity-50 disabled:cursor-not-allowed"
          aria-label={label}
        >
          {options.map((opt) => (
            <option value={opt}>{opt || `any`}</option>
          ))}
        </select>
      </label>
    </div>
  );
}
