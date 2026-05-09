import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_FILTERS,
  cardMatchesFilters,
  parseFiltersFromQuery,
  filtersToQueryString,
  agencyCounts,
  type SearchFilters,
} from "./search-filters.ts";
import type { CardMetadata } from "../data/types.ts";

/** Build a card with sensible defaults; tests override what they care about. */
function makeCard(overrides: Partial<CardMetadata> = {}): CardMetadata {
  return {
    card_id: "deadbeefcafe0001",
    title: "test card",
    asset_type: "PDF",
    agency: "FBI",
    release_date: "2026-01-01",
    incident_date: null,
    incident_location: null,
    redacted: false,
    description: null,
    asset_url: null,
    asset_filename: null,
    modal_image_url: null,
    dvids_video_id: null,
    video_title: null,
    pdf_pairing: null,
    video_pairing: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// cardMatchesFilters — the predicate at the heart of this feature.
// ---------------------------------------------------------------------------

test("cardMatchesFilters: empty filter state matches every card", () => {
  const card = makeCard();
  assert.equal(cardMatchesFilters(card, EMPTY_FILTERS), true);
});

test("cardMatchesFilters: agency filter is multi-select; OR within agencies", () => {
  const fbi = makeCard({ agency: "FBI" });
  const nasa = makeCard({ agency: "NASA" });
  const dos = makeCard({ agency: "DOS" });
  const filters: SearchFilters = { ...EMPTY_FILTERS, agencies: ["FBI", "NASA"] };
  assert.equal(cardMatchesFilters(fbi, filters), true);
  assert.equal(cardMatchesFilters(nasa, filters), true);
  assert.equal(cardMatchesFilters(dos, filters), false);
});

test("cardMatchesFilters: redactedOnly excludes non-redacted cards", () => {
  const filters: SearchFilters = { ...EMPTY_FILTERS, redactedOnly: true };
  assert.equal(cardMatchesFilters(makeCard({ redacted: true }), filters), true);
  assert.equal(cardMatchesFilters(makeCard({ redacted: false }), filters), false);
});

test("cardMatchesFilters: incident-date `from` excludes earlier dates AND null dates", () => {
  const filters: SearchFilters = { ...EMPTY_FILTERS, dateFrom: "1947-01-01" };
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1947-06-30" }), filters),
    true,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1946-12-31" }), filters),
    false,
  );
  // null incident_date is excluded as soon as ANY bound is set.
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: null }), filters),
    false,
  );
});

test("cardMatchesFilters: incident-date `to` excludes later dates AND null dates", () => {
  const filters: SearchFilters = { ...EMPTY_FILTERS, dateTo: "1949-12-31" };
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1949-12-31" }), filters),
    true,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1950-01-01" }), filters),
    false,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: null }), filters),
    false,
  );
});

test("cardMatchesFilters: null incident_date is INCLUDED when no date bound is set", () => {
  // The brief: "Cards with null/N/A incident date are EXCLUDED when ANY date
  // bound is set, included when neither is."
  const card = makeCard({ incident_date: null });
  assert.equal(cardMatchesFilters(card, EMPTY_FILTERS), true);
  // even with agency/redacted filters but no date bound, null dates pass.
  const f: SearchFilters = { ...EMPTY_FILTERS, agencies: ["FBI"] };
  assert.equal(cardMatchesFilters(card, f), true);
});

test("cardMatchesFilters: from + to bracket inclusively", () => {
  const filters: SearchFilters = {
    ...EMPTY_FILTERS,
    dateFrom: "1947-01-01",
    dateTo: "1949-12-31",
  };
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1947-01-01" }), filters),
    true,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1948-06-15" }), filters),
    true,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1949-12-31" }), filters),
    true,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1950-01-01" }), filters),
    false,
  );
});

test("cardMatchesFilters: filters AND together", () => {
  const filters: SearchFilters = {
    agencies: ["FBI"],
    dateFrom: "1947-01-01",
    dateTo: "1949-12-31",
    redactedOnly: true,
  };
  // matches all three predicates
  assert.equal(
    cardMatchesFilters(
      makeCard({ agency: "FBI", incident_date: "1948-01-01", redacted: true }),
      filters,
    ),
    true,
  );
  // wrong agency
  assert.equal(
    cardMatchesFilters(
      makeCard({ agency: "NASA", incident_date: "1948-01-01", redacted: true }),
      filters,
    ),
    false,
  );
  // not redacted
  assert.equal(
    cardMatchesFilters(
      makeCard({ agency: "FBI", incident_date: "1948-01-01", redacted: false }),
      filters,
    ),
    false,
  );
  // out of range
  assert.equal(
    cardMatchesFilters(
      makeCard({ agency: "FBI", incident_date: "1955-01-01", redacted: true }),
      filters,
    ),
    false,
  );
});

// ---------------------------------------------------------------------------
// URL state round-trip
// ---------------------------------------------------------------------------

test("filtersToQueryString: empty filters produces empty string (no q passed)", () => {
  assert.equal(filtersToQueryString(EMPTY_FILTERS), "");
});

test("filtersToQueryString: serialises the documented schema", () => {
  const f: SearchFilters = {
    agencies: ["FBI", "DOS"],
    dateFrom: "1947-01-01",
    dateTo: "1949-12-31",
    redactedOnly: true,
  };
  const qs = filtersToQueryString(f);
  // Order is stable so links are diffable.
  assert.equal(qs, "agency=FBI%2CDOS&from=1947-01-01&to=1949-12-31&redacted=1");
});

test("filtersToQueryString: omits keys that are at default values", () => {
  // Only agencies set — `from`/`to`/`redacted` should not appear.
  const f: SearchFilters = { ...EMPTY_FILTERS, agencies: ["FBI"] };
  assert.equal(filtersToQueryString(f), "agency=FBI");
});

test("parseFiltersFromQuery: round-trips a filter object losslessly", () => {
  const original: SearchFilters = {
    agencies: ["FBI", "DOS"],
    dateFrom: "1947-01-01",
    dateTo: "1949-12-31",
    redactedOnly: true,
  };
  const qs = filtersToQueryString(original);
  const parsed = parseFiltersFromQuery(qs);
  assert.deepEqual(parsed, original);
});

test("parseFiltersFromQuery: unknown / missing params yield empty filters", () => {
  assert.deepEqual(parseFiltersFromQuery(""), EMPTY_FILTERS);
  assert.deepEqual(parseFiltersFromQuery("q=hello"), EMPTY_FILTERS);
  // leading ? is tolerated
  assert.deepEqual(parseFiltersFromQuery("?q=hello"), EMPTY_FILTERS);
});

test("parseFiltersFromQuery: tolerates redacted=0 / =1 / absent", () => {
  assert.equal(parseFiltersFromQuery("redacted=1").redactedOnly, true);
  assert.equal(parseFiltersFromQuery("redacted=0").redactedOnly, false);
  assert.equal(parseFiltersFromQuery("redacted=true").redactedOnly, false); // strict: only "1" counts
  assert.equal(parseFiltersFromQuery("").redactedOnly, false);
});

test("parseFiltersFromQuery: agency list is comma-separated and trimmed", () => {
  assert.deepEqual(parseFiltersFromQuery("agency=FBI,DOS").agencies, ["FBI", "DOS"]);
  assert.deepEqual(parseFiltersFromQuery("agency=FBI, DOS ,NASA").agencies, [
    "FBI",
    "DOS",
    "NASA",
  ]);
  // empty entries are dropped
  assert.deepEqual(parseFiltersFromQuery("agency=,FBI,").agencies, ["FBI"]);
});

test("parseFiltersFromQuery: rejects malformed dates (non-YYYY-MM-DD)", () => {
  // Defensive: an invalid date silently becomes "" rather than throwing,
  // so a junk URL doesn't blow up the page.
  assert.equal(parseFiltersFromQuery("from=not-a-date").dateFrom, "");
  assert.equal(parseFiltersFromQuery("from=2026/05/09").dateFrom, "");
  assert.equal(parseFiltersFromQuery("from=2026-05-09").dateFrom, "2026-05-09");
});

// ---------------------------------------------------------------------------
// agencyCounts — for facet labels
// ---------------------------------------------------------------------------

test("agencyCounts: counts each agency across the supplied cards", () => {
  const cards = [
    makeCard({ agency: "FBI" }),
    makeCard({ agency: "FBI" }),
    makeCard({ agency: "NASA" }),
    makeCard({ agency: "DOS" }),
  ];
  const counts = agencyCounts(cards);
  assert.equal(counts.get("FBI"), 2);
  assert.equal(counts.get("NASA"), 1);
  assert.equal(counts.get("DOS"), 1);
});

test("agencyCounts: returns zero / undefined for an empty corpus", () => {
  const counts = agencyCounts([]);
  assert.equal(counts.size, 0);
});

// ---------------------------------------------------------------------------
// Edge-case predicate behaviors flagged in PR #5 review.
// ---------------------------------------------------------------------------

test("cardMatchesFilters: dateFrom > dateTo yields an empty intersection", () => {
  // A user typing/sharing a swapped range should match nothing — no card has
  // an incident_date that is BOTH ≥ 1970-01-01 AND ≤ 1947-01-01.
  const filters: SearchFilters = {
    ...EMPTY_FILTERS,
    dateFrom: "1970-01-01",
    dateTo: "1947-01-01",
  };
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1948-06-15" }), filters),
    false,
  );
  assert.equal(
    cardMatchesFilters(makeCard({ incident_date: "1971-01-01" }), filters),
    false,
  );
});

test("cardMatchesFilters: null incident_date passes when agency+redacted active but no date bound", () => {
  // Specifically asserts the "null is not excluded by non-date filters" path
  // — the predicate's structure implies it but we want a regression guard.
  const card = makeCard({
    incident_date: null,
    agency: "FBI",
    redacted: true,
  });
  const filters: SearchFilters = {
    ...EMPTY_FILTERS,
    agencies: ["FBI"],
    redactedOnly: true,
  };
  assert.equal(cardMatchesFilters(card, filters), true);
});

// ---------------------------------------------------------------------------
// Hardening: agency safety caps + calendrically-valid dates.
// ---------------------------------------------------------------------------

test("parseFiltersFromQuery: caps agencies array at 50 entries", () => {
  // SEC-001: oversized agency lists from a hostile share link must not
  // allocate huge arrays that get scanned via .includes() on every keystroke.
  const many = Array.from({ length: 200 }, (_, i) => `A${i}`).join(",");
  const parsed = parseFiltersFromQuery(`agency=${many}`);
  assert.equal(parsed.agencies.length, 50);
  // Order preserved: first 50 win.
  assert.equal(parsed.agencies[0], "A0");
  assert.equal(parsed.agencies[49], "A49");
});

test("parseFiltersFromQuery: drops agency entries longer than 100 chars", () => {
  // SEC-001: per-entry length cap.
  const longAgency = "X".repeat(150);
  const parsed = parseFiltersFromQuery(`agency=FBI,${longAgency},DOS`);
  assert.deepEqual(parsed.agencies, ["FBI", "DOS"]);
});

test("parseFiltersFromQuery: rejects calendrically-invalid dates that pass the regex", () => {
  // SEC-002: 9999-99-99 matches the regex but is not a real date. Reject so
  // a crafted share link doesn't silently zero out results.
  assert.equal(parseFiltersFromQuery("from=9999-99-99").dateFrom, "");
  assert.equal(parseFiltersFromQuery("from=2026-13-01").dateFrom, "");
  assert.equal(parseFiltersFromQuery("from=2026-02-30").dateFrom, "");
  // Real dates still pass.
  assert.equal(parseFiltersFromQuery("from=2026-02-28").dateFrom, "2026-02-28");
  assert.equal(parseFiltersFromQuery("to=2024-02-29").dateTo, "2024-02-29"); // leap year
});

test("filtersToQueryString: agency names containing commas survive a round-trip", () => {
  // F4 (P2): "DEPT, OF X".split(",") used to corrupt names. Encoding the
  // delimiter (we use %2C inside an entry, comma between entries) keeps
  // round-trips lossless.
  const original: SearchFilters = {
    ...EMPTY_FILTERS,
    agencies: ["DEPT, OF X", "FBI"],
  };
  const qs = filtersToQueryString(original);
  const parsed = parseFiltersFromQuery(qs);
  assert.deepEqual(parsed.agencies, ["DEPT, OF X", "FBI"]);
});

test("EMPTY_FILTERS: outer object is frozen so callers can't reassign properties", () => {
  // F6 (P2): the previous `Object.freeze(...) as SearchFilters` cast lost the
  // readonly typing. The exported type is now `Readonly<SearchFilters>` (and
  // a deep freeze is applied so the agencies array can't be mutated either),
  // pinning the contract in both the type system and at runtime.
  assert.throws(() => {
    // @ts-expect-error — caller mutation is exactly the misuse we want errors for.
    EMPTY_FILTERS.redactedOnly = true;
  });
  assert.throws(() => {
    // @ts-expect-error — see above.
    EMPTY_FILTERS.agencies.push("FBI");
  });
});
