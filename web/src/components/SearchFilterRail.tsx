import { useEffect, useState } from "preact/hooks";
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

// Pattern that lets the DateInput commit to filter state. Matches a complete
// `YYYY-MM-DD` OR an empty string (so clearing the input clears the bound).
// Intentionally NOT exported because the canonical predicate-side regex lives
// in search-filters.ts and is the same shape — duplicated here only because
// the input doesn't import from that module.
const COMMITTABLE_DATE_RE = /^(\d{4}-\d{2}-\d{2})?$/;

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
        <DateInput id="filter-date-from" label="from" value={from} onCommit={onFrom} />
        <DateInput id="filter-date-to" label="to" value={to} onCommit={onTo} />
      </div>
      <p class="mt-1.5 text-[10px] font-mono text-[color:var(--color-text-faint)] leading-snug">
        cards w/ no incident date are excluded when any bound is set
      </p>
    </div>
  );
}

/**
 * Date input that buffers the in-flight string locally and only commits to
 * the parent's filter state when the value is empty or a complete
 * `YYYY-MM-DD`. Why: the predicate compares dates lexicographically, so a
 * half-typed "194" would otherwise filter to "all cards ≥ 194" the moment
 * the user hits the fourth keystroke — clearly not what they meant. Buffering
 * defers the filter activation until the format is committable.
 */
function DateInput({
  id,
  label,
  value,
  onCommit,
}: {
  id: string;
  label: string;
  value: string;
  onCommit: (v: string) => void;
}) {
  // Local buffer mirrors the parent value when it changes externally (e.g.
  // RESET FILTERS, URL hydration), but otherwise tracks raw keystrokes.
  const [buffer, setBuffer] = useState(value);
  useEffect(() => {
    setBuffer(value);
  }, [value]);

  const onInput = (e: Event) => {
    const v = (e.target as HTMLInputElement).value.trim();
    setBuffer(v);
    if (COMMITTABLE_DATE_RE.test(v)) onCommit(v);
  };
  const onBlur = () => {
    // If the user tabs away with a half-typed value, don't leave it in the
    // input — snap back to whatever the committed parent state is so we
    // don't visually contradict the active filter.
    if (!COMMITTABLE_DATE_RE.test(buffer)) setBuffer(value);
  };

  return (
    <div>
      <label
        for={id}
        class="block text-[10px] font-mono text-[color:var(--color-text-faint)] mb-1"
      >
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={buffer}
        placeholder="YYYY-MM-DD"
        inputMode="numeric"
        pattern="\d{4}-\d{2}-\d{2}"
        onInput={onInput}
        onBlur={onBlur}
        class="w-full font-mono text-[12px]"
      />
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
