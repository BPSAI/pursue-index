import { useState } from "preact/hooks";
import {
  EMPTY_FILTERS,
  type SearchFilters,
} from "./search-filters.ts";

interface Props {
  filters: SearchFilters;
  setFilters: (f: SearchFilters) => void;
  /** All agencies present in the corpus (sorted). */
  agencies: string[];
  /** Per-agency total counts so users see "FBI (1,234)" alongside the pill. */
  agencyCounts: Map<string, number>;
}

/**
 * Faceted filter rail used by SearchIsland on /search. Renders as a left
 * column on desktop and a collapsible accordion on mobile (<768px) — the
 * collapsed state hides the entire rail body except for the toggle and the
 * active-filter summary so it doesn't push search results below the fold.
 */
export default function SearchFilterRail(p: Props) {
  // The accordion is open by default on desktop and closed on mobile. We
  // can't trivially detect viewport at hydrate time without flicker, so we
  // default to "open" everywhere and rely on `md:block` to keep the body
  // visible on desktop regardless of the toggle. The toggle only affects
  // the mobile presentation via the `data-collapsed` attribute.
  const [collapsed, setCollapsed] = useState(false);
  const activeCount = countActive(p.filters);

  return (
    <aside
      class="border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-4 space-y-4 self-start md:sticky md:top-4"
      aria-label="Search filters"
    >
      <div class="flex items-center justify-between">
        <h2 class="text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-signal-cyan)]">
          FILTERS
          {activeCount > 0 && (
            <span class="ml-2 text-[color:var(--color-signal-green)]">
              ({activeCount})
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          class="md:hidden text-[10px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-green)]"
          aria-expanded={!collapsed}
          aria-controls="search-filter-body"
        >
          {collapsed ? "▾ SHOW" : "▴ HIDE"}
        </button>
      </div>

      <div
        id="search-filter-body"
        class={`space-y-4 ${collapsed ? "hidden md:block" : "block"}`}
      >
        <AgencyFacet
          agencies={p.agencies}
          counts={p.agencyCounts}
          selected={p.filters.agencies}
          onToggle={(a) => p.setFilters(toggleAgency(p.filters, a))}
        />
        <DateRange
          from={p.filters.dateFrom}
          to={p.filters.dateTo}
          onFrom={(v) => p.setFilters({ ...p.filters, dateFrom: v })}
          onTo={(v) => p.setFilters({ ...p.filters, dateTo: v })}
        />
        <RedactedToggle
          checked={p.filters.redactedOnly}
          onChange={(v) => p.setFilters({ ...p.filters, redactedOnly: v })}
        />
        <button
          type="button"
          onClick={() => p.setFilters(EMPTY_FILTERS)}
          disabled={activeCount === 0}
          class="w-full px-2 py-1.5 text-[11px] font-mono uppercase tracking-[0.18em] border border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-amber)] hover:border-[color:var(--color-signal-amber)]/60 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-[color:var(--color-text-dim)] disabled:hover:border-[color:var(--color-border)] transition-colors"
        >
          RESET FILTERS
        </button>
      </div>
    </aside>
  );
}

function AgencyFacet({
  agencies,
  counts,
  selected,
  onToggle,
}: {
  agencies: string[];
  counts: Map<string, number>;
  selected: string[];
  onToggle: (a: string) => void;
}) {
  return (
    <div>
      <FacetLabel>AGENCY</FacetLabel>
      <div class="flex flex-wrap gap-1.5">
        {agencies.map((a) => {
          const isOn = selected.includes(a);
          const n = counts.get(a) ?? 0;
          return (
            <button
              type="button"
              onClick={() => onToggle(a)}
              aria-pressed={isOn}
              class={`px-2 py-1 text-[11px] font-mono uppercase tracking-[0.12em] border transition-colors ${
                isOn
                  ? "bg-[color:var(--color-signal-green)]/15 border-[color:var(--color-signal-green)]/60 text-[color:var(--color-signal-green)]"
                  : "bg-transparent border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-signal-green)]/40 hover:text-[color:var(--color-text-bright)]"
              }`}
            >
              {a}
              <span class="ml-1.5 text-[color:var(--color-text-faint)]">
                {n.toLocaleString()}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DateRange({
  from,
  to,
  onFrom,
  onTo,
}: {
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
}) {
  return (
    <div>
      <FacetLabel>INCIDENT DATE</FacetLabel>
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label
            for="filter-date-from"
            class="block text-[10px] font-mono text-[color:var(--color-text-faint)] mb-1"
          >
            from
          </label>
          <input
            id="filter-date-from"
            type="text"
            value={from}
            placeholder="YYYY-MM-DD"
            inputMode="numeric"
            pattern="\d{4}-\d{2}-\d{2}"
            onInput={(e) => onFrom((e.target as HTMLInputElement).value.trim())}
            class="w-full font-mono text-[12px]"
          />
        </div>
        <div>
          <label
            for="filter-date-to"
            class="block text-[10px] font-mono text-[color:var(--color-text-faint)] mb-1"
          >
            to
          </label>
          <input
            id="filter-date-to"
            type="text"
            value={to}
            placeholder="YYYY-MM-DD"
            inputMode="numeric"
            pattern="\d{4}-\d{2}-\d{2}"
            onInput={(e) => onTo((e.target as HTMLInputElement).value.trim())}
            class="w-full font-mono text-[12px]"
          />
        </div>
      </div>
      <p class="mt-1.5 text-[10px] font-mono text-[color:var(--color-text-faint)] leading-snug">
        cards w/ no incident date are excluded when any bound is set
      </p>
    </div>
  );
}

function RedactedToggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label class="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] cursor-pointer hover:text-[color:var(--color-text-bright)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange((e.target as HTMLInputElement).checked)}
        class="accent-[color:var(--color-signal-red)]"
      />
      REDACTED ONLY
    </label>
  );
}

function FacetLabel({ children }: { children: preact.ComponentChildren }) {
  return (
    <p class="text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-text-faint)] mb-2">
      {children}
    </p>
  );
}

function toggleAgency(filters: SearchFilters, agency: string): SearchFilters {
  const has = filters.agencies.includes(agency);
  return {
    ...filters,
    agencies: has
      ? filters.agencies.filter((a) => a !== agency)
      : [...filters.agencies, agency],
  };
}

function countActive(filters: SearchFilters): number {
  let n = 0;
  if (filters.agencies.length > 0) n++;
  if (filters.dateFrom) n++;
  if (filters.dateTo) n++;
  if (filters.redactedOnly) n++;
  return n;
}
