import { useEffect, useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";

interface Props {
  cards: CardMetadata[];
  base: string;
}

type SortKey = "title" | "release" | "incident" | "type";

const TYPE_BADGE: Record<string, string> = {
  PDF: "bg-red-900/40 text-red-300 ring-red-800",
  IMG: "bg-emerald-900/40 text-emerald-300 ring-emerald-800",
  VID: "bg-violet-900/40 text-violet-300 ring-violet-800",
};

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

  // Sync state to URL hash so links are shareable.
  useEffect(() => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (agency) params.set("agency", agency);
    if (type) params.set("type", type);
    if (redactedOnly) params.set("redacted", "1");
    if (sort !== "title") params.set("sort", sort);
    const next = params.toString();
    const url = next ? `#${next}` : window.location.pathname;
    history.replaceState(null, "", url);
  }, [query, agency, type, redactedOnly, sort]);

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
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end">
        <div class="flex-1">
          <label class="block text-xs uppercase tracking-wider text-neutral-500 mb-1">
            Search title / description / location
          </label>
          <input
            type="search"
            value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
            placeholder="e.g. roswell, debriefing, redacted…"
            class="w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-sm focus:border-neutral-500 focus:outline-none"
          />
        </div>
        <Selector label="Agency" value={agency} onChange={setAgency} options={["", ...agencies]} />
        <Selector label="Type" value={type} onChange={setType} options={["", "PDF", "IMG", "VID"]} />
        <Selector
          label="Sort"
          value={sort}
          onChange={(v) => setSort(v as SortKey)}
          options={["title", "release", "incident", "type"]}
        />
        <label class="flex items-center gap-2 text-sm text-neutral-300 lg:pb-2">
          <input
            type="checkbox"
            checked={redactedOnly}
            onChange={(e) => setRedactedOnly((e.target as HTMLInputElement).checked)}
            class="accent-red-500"
          />
          redacted only
        </label>
      </div>

      <div class="text-xs text-neutral-500">
        Showing <span class="text-neutral-300">{filtered.length}</span> /{" "}
        {cards.length} cards
      </div>

      <ul class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((c) => (
          <li
            class="rounded-lg border border-neutral-800 bg-neutral-925 hover:border-neutral-600 transition-colors"
          >
            <a href={`${base}/card/${c.card_id}`} class="block p-4 space-y-2">
              <div class="flex items-center gap-2 flex-wrap">
                <span
                  class={`text-[10px] font-semibold uppercase tracking-wider ring-1 px-1.5 py-0.5 rounded ${TYPE_BADGE[c.asset_type] ?? ""}`}
                >
                  {c.asset_type}
                </span>
                <span class="text-[10px] text-neutral-500 uppercase tracking-wider">
                  {c.agency}
                </span>
                {c.redacted && (
                  <span class="text-[10px] uppercase tracking-wider text-red-400 font-semibold">
                    redacted
                  </span>
                )}
              </div>
              <h3 class="text-sm font-medium leading-snug text-neutral-100 line-clamp-3">
                {c.title}
              </h3>
              <div class="text-xs text-neutral-500 flex items-center gap-3">
                {c.incident_date && <span>incident: {c.incident_date}</span>}
                {c.incident_location && <span class="truncate">📍 {c.incident_location}</span>}
              </div>
              {c.description && (
                <p class="text-xs text-neutral-400 line-clamp-3">{c.description}</p>
              )}
            </a>
          </li>
        ))}
      </ul>

      {filtered.length === 0 && (
        <p class="text-sm text-neutral-500 text-center py-12">
          No cards match. Loosen a filter.
        </p>
      )}
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
      <label class="block text-xs uppercase tracking-wider text-neutral-500 mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
        class="rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-sm focus:border-neutral-500 focus:outline-none"
      >
        {options.map((opt) => (
          <option value={opt}>{opt || `any ${label.toLowerCase()}`}</option>
        ))}
      </select>
    </div>
  );
}
