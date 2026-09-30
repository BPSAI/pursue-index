/**
 * The /methodology denominators sentence, built from qc-coverage.json.
 *
 * Fixtures only: the figures come from the payload the page imports, so the
 * tests pin how a payload is described, not what the corpus currently holds.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { describeQcCoverage, type QcCoverage, type QcCoverageCard } from "./qc-coverage.ts";

function card(card_id: string, asset_types: string[], status: string, vision?: number[]): QcCoverageCard {
  return vision
    ? { card_id, asset_types, status, vision_text_pages: vision }
    : { card_id, asset_types, status };
}

function payload(cards: QcCoverageCard[]): QcCoverage {
  const status_counts: Record<string, number> = {
    judged: 0,
    unverified_transcript: 0,
    unverified_vision: 0,
    no_text: 0,
    unverified_other: 0,
  };
  for (const c of cards) status_counts[c.status] += 1;
  const withVision = cards.filter((c) => c.vision_text_pages);
  return {
    total_cards: cards.length,
    status_counts,
    unverified_other: cards.filter((c) => c.status === "unverified_other").map((c) => c.card_id),
    vision_text_pages_in_judged_cards: {
      cards: withVision.length,
      pages: withVision.reduce((n, c) => n + (c.vision_text_pages?.length ?? 0), 0),
    },
    cards,
  };
}

test("describeQcCoverage: states every denominator from the payload", () => {
  const doc = payload([
    card("p1", ["PDF"], "judged"),
    card("p2", ["PDF", "VID"], "judged", [3, 4]),
    card("p3", ["PDF"], "judged", [1]),
    card("i1", ["IMG"], "unverified_vision"),
    card("a1", ["AUD"], "unverified_transcript"),
    card("a2", ["AUD"], "unverified_transcript"),
    card("v1", ["VID"], "no_text"),
    card("v2", ["VID"], "no_text"),
  ]);
  assert.deepEqual(describeQcCoverage(doc), [
    "Of 8 cards, 3 (all PDF documents with OCR text) are QC-judged page by page.",
    "1 image description and 2 audio transcripts are not yet independently verified.",
    "2 videos carry no text.",
    "Within the judged documents, 3 image-only pages across 2 cards carry our vision description instead of OCR; those descriptions are not yet independently verified.",
  ]);
});

test("describeQcCoverage: does not call the judged set 'all PDF documents' when a PDF is unjudged", () => {
  const doc = payload([
    card("p1", ["PDF"], "judged"),
    card("p2", ["PDF"], "unverified_other"),
    card("v1", ["VID"], "no_text"),
    card("a1", ["AUD"], "no_text"),
  ]);
  const lines = describeQcCoverage(doc);
  assert.equal(lines[0], "Of 4 cards, 1 is QC-judged page by page.");
  assert.ok(lines.includes("2 cards carry no text."));
  assert.ok(lines.includes("1 other card is not yet verified: p2."));
});

test("describeQcCoverage: omits clauses whose count is zero", () => {
  const doc = payload([card("p1", ["PDF"], "judged")]);
  assert.deepEqual(describeQcCoverage(doc), [
    "Of 1 card, 1 (all PDF documents with OCR text) is QC-judged page by page.",
  ]);
});

test("describeQcCoverage: formats thousands", () => {
  const cards = Array.from({ length: 1200 }, (_, i) => card(`v${i}`, ["VID"], "no_text"));
  assert.equal(describeQcCoverage(payload(cards))[0], "Of 1,200 cards, 0 are QC-judged page by page.");
});
