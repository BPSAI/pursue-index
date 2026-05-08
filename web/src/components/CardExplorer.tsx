import { useEffect, useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";

interface Props {
  cards: CardMetadata[];
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

export default function CardExplorer({ cards, base }: Props) {
  const agencies = useMemo(
    () => Array.from(new Set(cards.map((c) => c.agency))).sort(),
    [cards],
  );

  const [query, setQuery] = useState("");
  const [agency, setAgency] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [redactedOnly, setRedactedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("title");
  const [view, setView] = useState<ViewMode>("cards");

  // Sync state to URL hash so links are shareable.
  useEffect(() => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (agency) params.set("agency", agency);
    if (type) params.set("type", type);
    if (redactedOnly) params.set("redacted", "1");
    if (sort !== "title") params.set("sort", sort);
    if (view !== "cards") params.set("view", view);
    const next = params.toString();
    const url = next ? `#${next}` : window.location.pathname;
    history.replaceState(null, "", url);
  }, [query, agency, type, redactedOnly, sort, view]);

  // Hydrate from hash on mount.
  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    if (!hash) return;
    const params = new URLSearchParams(hash);
    if (params.get("q")) setQuery(params.get("q")!);
    if (params.get("agency")) setAgency(params.get("agency")!);
    if (params.get("type")) setType(params.get("type")!);
    if (params.get("redacted") === "1") setRedactedOnly(true);
    const s = params.get("sort");
    if (s === "release" || s === "incident" || s === "type") setSort(s);
    const v = params.get("view");
    if (v === "table" || v === "cards") setView(v);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = cards.filter((c) => {
      if (agency && c.agency !== agency) return false;
      if (type && c.asset_type !== type) return false;
      if (redactedOnly && !c.redacted) return false;
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
  }, [cards, query, agency, type, redactedOnly, sort]);

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
        sort={sort}
        setSort={setSort}
        agencies={agencies}
      />

      <div class="flex items-center justify-between border-b border-[color:var(--color-border)] pb-2">
        <div class="text-[11px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-green)]">{filtered.length}</span>
          <span class="mx-1 text-[color:var(--color-text-faint)]">/</span>
          {cards.length} RECORDS
        </div>
        <ViewToggle view={view} setView={setView} />
      </div>

      {view === "cards" ? (
        <CardGrid filtered={filtered} base={base} />
      ) : (
        <TableView filtered={filtered} base={base} />
      )}

      {filtered.length === 0 && (
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
  sort: SortKey;
  setSort: (v: SortKey) => void;
  agencies: string[];
}

function Filters(p: FiltersProps) {
  return (
    <div class="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_auto_auto_auto_auto] lg:items-end">
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
      <Selector label="TYPE" value={p.type} onChange={p.setType} options={["", "PDF", "IMG", "VID"]} />
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

function CardGrid({ filtered, base }: { filtered: CardMetadata[]; base: string }) {
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
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div>
      <label class="block text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-text-faint)] mb-1.5">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
      >
        {options.map((opt) => (
          <option value={opt}>{opt || `any`}</option>
        ))}
      </select>
    </div>
  );
}
