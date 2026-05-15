import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildTimelineCards,
  dateToYearPos,
  detectPrecision,
  summary,
  yearSpan,
  type DateEntry,
} from "./timeline-helpers.ts";
import type { CardMetadata } from "../data/types.ts";

function card(id: string, agency = "FBI"): CardMetadata {
  return {
    card_id: id,
    title: `Card ${id}`,
    asset_type: "PDF",
    agency,
    release_date: null,
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
    image_alt_text: null,
    image_virin: null,
    original_classification: null,
  };
}

// --- dateToYearPos ---

test("dateToYearPos: null/undefined → null", () => {
  assert.equal(dateToYearPos(null), null);
  assert.equal(dateToYearPos(undefined), null);
  assert.equal(dateToYearPos(""), null);
});

test("dateToYearPos: YYYY-MM-DD → year + fractional", () => {
  // 1947-07-08 ≈ 1947 + 6/12 + 7/365 ≈ 1947.519
  const v = dateToYearPos("1947-07-08");
  assert.ok(v != null && v > 1947.49 && v < 1947.55);
});

test("dateToYearPos: YYYY-MM → mid-month", () => {
  // 1969-11 (mid-month, day=15) ≈ 1969 + 10/12 + 14/365 ≈ 1969.872
  const v = dateToYearPos("1969-11");
  assert.ok(v != null && v > 1969.85 && v < 1969.92);
});

test("dateToYearPos: YYYY → mid-year", () => {
  assert.equal(dateToYearPos("1965"), 1965.5);
});

test("dateToYearPos: garbage → null", () => {
  assert.equal(dateToYearPos("around 1947"), null);
});

// --- detectPrecision ---

test("detectPrecision: range > day > month > year > none", () => {
  const base: DateEntry = { card_id: "x", display_date: null, display_date_range: null };
  assert.equal(detectPrecision({ ...base, display_date_range: ["1947-01", "1947-12"] }), "range");
  assert.equal(detectPrecision({ ...base, display_date: "1947-07-08" }), "day");
  assert.equal(detectPrecision({ ...base, display_date: "1969-11" }), "month");
  assert.equal(detectPrecision({ ...base, display_date: "1965" }), "year");
  assert.equal(detectPrecision({ ...base }), "none");
});

// --- buildTimelineCards ---

test("buildTimelineCards: approved beats proposal beats none", () => {
  const cards = [card("aaa"), card("bbb"), card("ccc")];
  const approved: Record<string, DateEntry> = {
    aaa: { card_id: "aaa", display_date: "1947-07-08", display_date_range: null },
  };
  const proposals: Record<string, DateEntry> = {
    aaa: { card_id: "aaa", display_date: "1947-08-15", display_date_range: null }, // approved wins
    bbb: { card_id: "bbb", display_date: "1969-11", display_date_range: null },
  };
  const out = buildTimelineCards(cards, approved, proposals);
  assert.equal(out[0].source, "approved");
  assert.equal(out[0].display_date, "1947-07-08");
  assert.equal(out[1].source, "proposal");
  assert.equal(out[1].display_date, "1969-11");
  assert.equal(out[2].source, "none");
  assert.equal(out[2].display_date, null);
});

test("buildTimelineCards: abstention with reason renders precision=none + abstention text", () => {
  const cards = [card("aaa")];
  const approved: Record<string, DateEntry> = {
    aaa: {
      card_id: "aaa",
      display_date: null,
      display_date_range: null,
      display_date_abstention: "Decade-spanning file; no single date",
    },
  };
  const out = buildTimelineCards(cards, approved, {});
  assert.equal(out[0].source, "approved");
  assert.equal(out[0].precision, "none");
  assert.equal(out[0].yearPos, null);
  assert.ok((out[0].abstention || "").includes("Decade-spanning"));
});

// --- yearSpan ---

test("yearSpan: empty → null", () => {
  assert.equal(yearSpan([]), null);
});

test("yearSpan: returns [floor(min), ceil(max)]", () => {
  const cards = [card("a"), card("b"), card("c")];
  const items = buildTimelineCards(
    cards,
    {},
    {
      a: { card_id: "a", display_date: "1947-07-08", display_date_range: null },
      b: { card_id: "b", display_date: "1965", display_date_range: null },
      c: { card_id: "c", display_date: "2023-10-24", display_date_range: null },
    },
  );
  const span = yearSpan(items);
  assert.ok(span);
  assert.equal(span![0], 1947);
  assert.equal(span![1], 2024);
});

// --- summary ---

test("summary: counts approved + proposal + abstained + undated", () => {
  const cards = [card("a"), card("b"), card("c"), card("d")];
  const approved: Record<string, DateEntry> = {
    a: { card_id: "a", display_date: "1947-07-08", display_date_range: null },
  };
  const proposals: Record<string, DateEntry> = {
    b: { card_id: "b", display_date: "1965", display_date_range: null },
    c: {
      card_id: "c",
      display_date: null,
      display_date_range: null,
      display_date_abstention: "no defensible date",
    },
    // d gets no entry → undated
  };
  const items = buildTimelineCards(cards, approved, proposals);
  const s = summary(items);
  assert.equal(s.total, 4);
  assert.equal(s.approved, 1);
  assert.equal(s.proposal, 2);
  assert.equal(s.abstained, 1);
  assert.equal(s.undated, 1);
});
