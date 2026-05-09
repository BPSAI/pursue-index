/**
 * Presentational chrome around the SearchIsland result list.
 *
 * Extracted from SearchIsland (PR #5 review F5) so the parent can stay focused
 * on "fetch index + manage state + lay out the page" while these self-contained
 * widgets handle filter-state visualisation. They have no side effects and read
 * filter state via props — keeping the dependency direction one-way.
 */
import type { SearchFilters } from "./search-filters.ts";

/**
 * Pure check: does the user have at least one active filter clause? Lives in
 * this module (alongside its sole consumers) rather than in `search-filters.ts`
 * to keep that file focused on the predicate / URL layer.
 */
export function hasActiveFilters(f: SearchFilters): boolean {
  return (
    f.agencies.length > 0 ||
    f.dateFrom !== "" ||
    f.dateTo !== "" ||
    f.redactedOnly
  );
}

/**
 * Sticky chip showing the currently-active filter clauses with a one-click
 * clear. Renders nothing when no filters are active.
 */
export function ActiveFilterBadge({
  filters,
  onClear,
}: {
  filters: SearchFilters;
  onClear: () => void;
}) {
  if (!hasActiveFilters(filters)) return null;
  const parts: string[] = [];
  if (filters.agencies.length > 0) parts.push(filters.agencies.join(" + "));
  if (filters.dateFrom || filters.dateTo) {
    parts.push(`${filters.dateFrom || "…"} → ${filters.dateTo || "…"}`);
  }
  if (filters.redactedOnly) parts.push("redacted only");
  return (
    <div class="flex items-center gap-2 flex-wrap text-[11px] font-mono uppercase tracking-[0.15em] border border-[color:var(--color-signal-cyan)]/40 bg-[color:var(--color-signal-cyan)]/5 px-3 py-2">
      <span class="text-[color:var(--color-signal-cyan)]">FILTERS:</span>
      <span class="text-[color:var(--color-text-bright)] normal-case tracking-normal">
        {parts.join(" · ")}
      </span>
      <button
        type="button"
        onClick={onClear}
        class="ml-auto text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-amber)]"
      >
        [clear]
      </button>
    </div>
  );
}

/**
 * Banner for the chat surface explaining that active URL-filter state is
 * scoping the displayed citation list, not the model's retrieval context.
 * Mirrors ActiveFilterBadge but with a longer caption since the chat-side
 * boundary is non-obvious. PR #5 review F10.
 */
export function FilterContextBanner({
  filters,
  onClear,
}: {
  filters: SearchFilters;
  onClear: () => void;
}) {
  if (!hasActiveFilters(filters)) return null;
  const parts: string[] = [];
  if (filters.agencies.length > 0) parts.push(filters.agencies.join(" + "));
  if (filters.dateFrom || filters.dateTo) {
    parts.push(`${filters.dateFrom || "…"} → ${filters.dateTo || "…"}`);
  }
  if (filters.redactedOnly) parts.push("redacted only");
  return (
    <div class="mb-3 border border-[color:var(--color-signal-cyan)]/40 bg-[color:var(--color-signal-cyan)]/5 px-3 py-2 text-[11px] font-mono uppercase tracking-[0.15em]">
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-[color:var(--color-signal-cyan)]">SOURCES SCOPED:</span>
        <span class="text-[color:var(--color-text-bright)] normal-case tracking-normal">
          {parts.join(" · ")}
        </span>
        <button
          type="button"
          onClick={onClear}
          class="ml-auto text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-amber)]"
        >
          [clear]
        </button>
      </div>
      <p class="mt-1 normal-case tracking-normal text-[10px] text-[color:var(--color-text-faint)]">
        Filters scope the displayed citation list only. The retrieval model
        still searches the full corpus when answering.
      </p>
    </div>
  );
}

/**
 * Empty-results affordance. Distinguishes "no results AND filters are active"
 * (offer a clear-filters CTA) from "no results, no filters" (terse one-liner).
 */
export function EmptyResults({
  filtersOn,
  hasActive,
  onClear,
}: {
  filtersOn: boolean;
  hasActive: boolean;
  onClear: () => void;
}) {
  if (filtersOn && hasActive) {
    return (
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-5 text-center font-mono text-sm text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-amber)]">[NO MATCH]</span>
        <span class="mx-2">no results match these filters</span>
        <span class="text-[color:var(--color-text-faint)]">·</span>
        <button
          type="button"
          onClick={onClear}
          class="ml-2 text-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-signal-green)] underline-offset-2 hover:underline"
        >
          clear filters
        </button>
      </div>
    );
  }
  return (
    <p class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)]">
      [no results]
    </p>
  );
}
