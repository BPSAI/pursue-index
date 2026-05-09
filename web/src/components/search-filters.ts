/**
 * Pure-function helpers for the /search filter rail.
 *
 * Kept entirely free of preact/DOM imports so it's trivially unit-testable
 * with `node:test` and is safe to run in worker / SSR contexts later if we
 * decide to push filtering server-side.
 *
 * Design choices worth flagging for reviewers:
 *
 * 1. The predicate excludes cards with `incident_date === null` whenever
 *    EITHER `dateFrom` OR `dateTo` is set. The brief is explicit on this;
 *    the alternative (treating null as "always-in") meant a user filtering
 *    to "1947" would still see the 60% of cards with no incident date,
 *    which defeats the purpose of the facet.
 *
 * 2. Date strings are compared lexicographically. ISO `YYYY-MM-DD` sorts
 *    correctly as ASCII so we avoid the cost (and timezone bugs) of
 *    parsing into Date objects. `parseFiltersFromQuery` enforces the
 *    format on the way in.
 *
 * 3. URL-state schema: `?q=foo&agency=FBI,DOS&from=1947-01-01&to=1949-12-31&redacted=1`.
 *    Comma-separated agencies (rather than repeated `agency=` params)
 *    keeps shareable links short and matches CardExplorer's hash-state
 *    convention. `q` is owned by the search input, not these helpers.
 */
import type { CardMetadata } from "../data/types.ts";

export interface SearchFilters {
  /** Multi-select. Empty array means "any agency". */
  agencies: string[];
  /** ISO `YYYY-MM-DD` lower bound (inclusive); empty string means unbounded. */
  dateFrom: string;
  /** ISO `YYYY-MM-DD` upper bound (inclusive); empty string means unbounded. */
  dateTo: string;
  /** When true, only cards with `redacted === true` pass. */
  redactedOnly: boolean;
}

export const EMPTY_FILTERS: SearchFilters = Object.freeze({
  agencies: [] as string[],
  dateFrom: "",
  dateTo: "",
  redactedOnly: false,
}) as SearchFilters;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Returns true iff the given card passes ALL of the active filter clauses.
 * Cards with a null `incident_date` are excluded the moment any date bound
 * is set; otherwise they pass.
 */
export function cardMatchesFilters(
  card: CardMetadata,
  filters: SearchFilters,
): boolean {
  if (filters.agencies.length > 0 && !filters.agencies.includes(card.agency)) {
    return false;
  }
  if (filters.redactedOnly && !card.redacted) {
    return false;
  }
  const hasDateBound = filters.dateFrom !== "" || filters.dateTo !== "";
  if (hasDateBound) {
    if (!card.incident_date) return false;
    if (filters.dateFrom && card.incident_date < filters.dateFrom) return false;
    if (filters.dateTo && card.incident_date > filters.dateTo) return false;
  }
  return true;
}

/**
 * Serialise filters into a URLSearchParams-compatible string, omitting any
 * key that's at its default. Returns "" when no filters are active so the
 * caller can decide whether to drop the leading "?".
 */
export function filtersToQueryString(filters: SearchFilters): string {
  const params = new URLSearchParams();
  if (filters.agencies.length > 0) {
    params.set("agency", filters.agencies.join(","));
  }
  if (filters.dateFrom) params.set("from", filters.dateFrom);
  if (filters.dateTo) params.set("to", filters.dateTo);
  if (filters.redactedOnly) params.set("redacted", "1");
  return params.toString();
}

/**
 * Parse our filter schema out of a URL query string (with or without the
 * leading "?"). Unknown / missing keys map to defaults; malformed dates are
 * silently dropped so a junk URL doesn't render an error state.
 */
export function parseFiltersFromQuery(query: string): SearchFilters {
  const trimmed = query.startsWith("?") ? query.slice(1) : query;
  const params = new URLSearchParams(trimmed);
  const agencyRaw = params.get("agency") ?? "";
  const agencies = agencyRaw
    .split(",")
    .map((a) => a.trim())
    .filter((a) => a.length > 0);
  const fromRaw = params.get("from") ?? "";
  const toRaw = params.get("to") ?? "";
  return {
    agencies,
    dateFrom: DATE_RE.test(fromRaw) ? fromRaw : "",
    dateTo: DATE_RE.test(toRaw) ? toRaw : "",
    redactedOnly: params.get("redacted") === "1",
  };
}

/**
 * Count cards per agency across the corpus. Used for facet labels so users
 * see "FBI (1,234)" next to each pill.
 */
export function agencyCounts(cards: CardMetadata[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const c of cards) {
    counts.set(c.agency, (counts.get(c.agency) ?? 0) + 1);
  }
  return counts;
}
