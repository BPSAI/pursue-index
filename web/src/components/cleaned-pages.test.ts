import { test } from "node:test";
import assert from "node:assert/strict";
import {
  filterCleanedPages,
  requiresUiNotice,
  CLEANUP_SKIP_REASONS,
  type CleanedPayload,
  type CleanedPage,
} from "./cleaned-pages.ts";

function makePayload(pages: Partial<CleanedPage>[]): CleanedPayload {
  return {
    meta: {
      generated_at: "2026-05-09T00:00:00Z",
      source: "pilot-30-cards",
      cards_covered: Array.from(new Set(pages.map((p) => p.card_id!))),
      page_count: pages.length,
      model_id: "claude-haiku-4-5-20251001",
      prompt_sha256: "abc",
    },
    pages: pages.map((p) => {
      const row: CleanedPage = {
        id: p.id ?? `${p.card_id}-p${p.page}`,
        card_id: p.card_id!,
        page: p.page!,
        title: p.title ?? "",
        text: p.text ?? "",
        model_id: p.model_id ?? "claude-haiku-4-5-20251001",
        prompt_sha256: p.prompt_sha256 ?? "abc",
        input_sha256: p.input_sha256 ?? "",
        output_sha256: p.output_sha256 ?? "",
        generated_at: p.generated_at ?? "",
      };
      if (p.cleanup_skipped) row.cleanup_skipped = p.cleanup_skipped;
      return row;
    }),
  };
}

test("filterCleanedPages: returns only the pages for the asked card_id", () => {
  const payload = makePayload([
    { card_id: "c1", page: 1, text: "p1" },
    { card_id: "c1", page: 2, text: "p2" },
    { card_id: "c2", page: 1, text: "other" },
  ]);
  const out = filterCleanedPages(payload, "c1");
  assert.equal(out.length, 2);
  assert.equal(out[0].card_id, "c1");
  assert.equal(out[1].card_id, "c1");
});

test("filterCleanedPages: sorts by page number", () => {
  const payload = makePayload([
    { card_id: "c1", page: 3, text: "p3" },
    { card_id: "c1", page: 1, text: "p1" },
    { card_id: "c1", page: 2, text: "p2" },
  ]);
  const out = filterCleanedPages(payload, "c1");
  assert.deepEqual(out.map((p) => p.page), [1, 2, 3]);
});

test("filterCleanedPages: returns empty list when card has no cleaned pages", () => {
  const payload = makePayload([{ card_id: "c1", page: 1, text: "p" }]);
  assert.deepEqual(filterCleanedPages(payload, "c-other"), []);
});

test("filterCleanedPages: null payload → empty (handles fetch failure)", () => {
  assert.deepEqual(filterCleanedPages(null, "c1"), []);
});

test("filterCleanedPages: propagates cleanup_skipped flag on skipped pages", () => {
  // Codex P1 follow-up: the build script now preserves rows with
  // `cleanup_skipped` set ("empty_input", "length_divergence", or
  // "content_filter") so pages-cleaned.json keeps the same page
  // sequence as pages.json. The flag must reach the UI so it can render
  // an appropriate notice. All three reasons must round-trip so any
  // future regression in the filter layer surfaces here, not at the
  // user-visible CardReaderView render boundary.
  const payload = makePayload([
    { card_id: "c1", page: 1, text: "normal cleaned" },
    {
      card_id: "c1",
      page: 2,
      text: "",
      cleanup_skipped: "length_divergence",
    },
    {
      card_id: "c1",
      page: 3,
      text: "",
      cleanup_skipped: "empty_input",
    },
    {
      card_id: "c1",
      page: 4,
      text: "",
      cleanup_skipped: "content_filter",
    },
  ]);
  const out = filterCleanedPages(payload, "c1");
  assert.equal(out.length, 4);
  assert.equal(out[0].cleanup_skipped, undefined);
  assert.equal(out[1].cleanup_skipped, "length_divergence");
  assert.equal(out[2].cleanup_skipped, "empty_input");
  assert.equal(out[3].cleanup_skipped, "content_filter");
});

test("requiresUiNotice: gates the cleanup-notice render path", () => {
  // vaivora P0: the CardCleanedView forwarder and CardReaderView render
  // branch must agree on which skip reasons require a notice. Funnel
  // both call sites through this predicate so a future fourth reason
  // is a single-line opt-in (or omission).
  //
  //   - length_divergence + content_filter → notice
  //   - empty_input                         → no notice (falls through
  //                                            to the generic [BLANK])
  //   - undefined / unknown                 → no notice
  assert.equal(requiresUiNotice("length_divergence"), true);
  assert.equal(requiresUiNotice("content_filter"), true);
  assert.equal(requiresUiNotice("empty_input"), false);
  assert.equal(requiresUiNotice(undefined), false);
  assert.equal(requiresUiNotice("unknown_future_reason"), false);
});

test("CLEANUP_SKIP_REASONS: stays aligned with Python-side constant", () => {
  // Documents the contract between
  // `scripts/build_pages_cleaned.py::CLEANUP_SKIP_REASONS` and this
  // module — they must list the same three values in the same intent.
  // If a fourth reason is added, this test forces both sides to be
  // updated together (run `pytest -k cleanup_skip_reasons` to confirm
  // the Python side carries the matching string).
  assert.deepEqual(
    [...CLEANUP_SKIP_REASONS],
    ["empty_input", "length_divergence", "content_filter"],
  );
});

test(
  "filterCleanedPages: page-N alignment with raw mirror across cleanup_skipped rows",
  () => {
    // Contract: when the cleaned mirror preserves all rows (including
    // cleanup_skipped ones), `pages[activePage-1]` resolves to the same
    // source page as it would in the raw mirror. Dropping any row would
    // shift later pages by 1 and break #page-N deep links.
    const payload = makePayload([
      { card_id: "c1", page: 1, text: "p1" },
      { card_id: "c1", page: 2, text: "", cleanup_skipped: "empty_input" },
      {
        card_id: "c1",
        page: 3,
        text: "",
        cleanup_skipped: "length_divergence",
      },
      { card_id: "c1", page: 4, text: "p4" },
    ]);
    const out = filterCleanedPages(payload, "c1");
    // Array-indexed pagination: pages[i-1].page === i for all four pages.
    assert.deepEqual(out.map((p) => p.page), [1, 2, 3, 4]);
    // Indices line up exactly so a #page-3 deep link reads
    // pages[2], which is the length_divergence page (NOT the page-4
    // content that would surface if the row had been dropped).
    assert.equal(out[2].cleanup_skipped, "length_divergence");
    assert.equal(out[2].text, "");
  },
);
