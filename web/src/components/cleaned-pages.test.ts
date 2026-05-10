import { test } from "node:test";
import assert from "node:assert/strict";
import {
  filterCleanedPages,
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
    pages: pages.map((p) => ({
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
    })),
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
