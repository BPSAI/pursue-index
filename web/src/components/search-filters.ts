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
 *    format AND calendric validity on the way in.
 *
 * 3. URL-state schema: `?q=foo&agency=FBI,DOS&from=1947-01-01&to=1949-12-31&redacted=1`.
 *    Comma-separated agencies (rather than repeated `agency=` params)
 *    keeps shareable links short. Each agency entry is `encodeURIComponent`-
 *    encoded so names containing commas (e.g. "DEPT, OF X") round-trip
 *    losslessly. `q` is owned by the search input, not these helpers.
 *
 * 4. Hostile-input bounds: agencies parsed from URL are capped at
 *    `MAX_AGENCY_ENTRIES` and each entry at `MAX_AGENCY_LEN` so a crafted
 *    share link can't allocate huge arrays that we then `.includes()` on
 *    every keystroke. See SEC-001 in the PR #5 security review.
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

/**
 * Deep-frozen, statically-typed default. Typed as `Readonly<SearchFilters>`
 * so TS callers must spread (`{...EMPTY_FILTERS, agencies: [...]}`) instead
 * of mutating the shared singleton — and the runtime freeze backs that
 * contract for any `as SearchFilters`-style escapes.
 */
export const EMPTY_FILTERS: Readonly<SearchFilters> = Object.freeze({
  agencies: Object.freeze([] as string[]) as string[],
  dateFrom: "",
  dateTo: "",
  redactedOnly: false,
});

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_AGENCY_ENTRIES = 50;
const MAX_AGENCY_LEN = 100;

/**
 * Calendrically validate an ISO `YYYY-MM-DD` string. Catches `9999-99-99`
 * and `2026-02-30` which pass the regex but aren't real dates. We re-parse
 * via `Date.UTC` and verify the round-trip — purely a validation step,
 * not a path used by the comparator (which stays lex-only to avoid
 * timezone bugs). See SEC-002 in the PR #5 security review.
 */
function isValidISODate(raw: string): boolean {
  if (!DATE_RE.test(raw)) return false;
  const [y, m, d] = raw.split("-").map(Number);
  // Date.UTC normalizes invalid components (Feb 30 → Mar 2), so we round-trip
  // and confirm the components survive unchanged.
  const t = Date.UTC(y, m - 1, d);
  if (Number.isNaN(t)) return false;
  const dt = new Date(t);
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

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
 *
 * Agency names are individually `encodeURIComponent`-encoded before being
 * comma-joined so that names containing literal commas (e.g. "DEPT, OF X")
 * survive the parse. Decoding happens in `parseFiltersFromQuery`.
 */
export function filtersToQueryString(filters: SearchFilters): string {
  const params = new URLSearchParams();
  if (filters.agencies.length > 0) {
    params.set("agency", filters.agencies.map(encodeURIComponent).join(","));
  }
  if (filters.dateFrom) params.set("from", filters.dateFrom);
  if (filters.dateTo) params.set("to", filters.dateTo);
  if (filters.redactedOnly) params.set("redacted", "1");
  return params.toString();
}

/**
 * Parse our filter schema out of a URL query string (with or without the
 * leading "?"). Unknown / missing keys map to defaults; malformed or
 * calendrically-invalid dates are silently dropped so a junk URL doesn't
 * render an error state. Agency lists are capped at `MAX_AGENCY_ENTRIES`
 * entries × `MAX_AGENCY_LEN` chars each (SEC-001 hardening).
 */
export function parseFiltersFromQuery(query: string): SearchFilters {
  const trimmed = query.startsWith("?") ? query.slice(1) : query;
  const params = new URLSearchParams(trimmed);
  const agencyRaw = params.get("agency") ?? "";
  const agencies = parseAgencyList(agencyRaw);
  const fromRaw = params.get("from") ?? "";
  const toRaw = params.get("to") ?? "";
  return {
    agencies,
    dateFrom: isValidISODate(fromRaw) ? fromRaw : "",
    dateTo: isValidISODate(toRaw) ? toRaw : "",
    redactedOnly: params.get("redacted") === "1",
  };
}

/**
 * Helper extracted from `parseFiltersFromQuery` so the entry-cap / length-cap
 * / decoding logic is testable in isolation and the parent function stays
 * focused on URL-key dispatch.
 */
function parseAgencyList(raw: string): string[] {
  if (!raw) return [];
  const parts = raw.split(",");
  const out: string[] = [];
  for (const part of parts) {
    if (out.length >= MAX_AGENCY_ENTRIES) break;
    let value = part.trim();
    if (!value) continue;
    // Tolerate both encoded ("DEPT%2C%20OF%20X") and raw ("DEPT") segments —
    // decodeURIComponent throws on malformed escapes, so guard.
    try {
      value = decodeURIComponent(value);
    } catch {
      // leave `value` as-is; it'll still be subject to the length cap below
    }
    if (value.length === 0 || value.length > MAX_AGENCY_LEN) continue;
    out.push(value);
  }
  return out;
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
