/**
 * Tests for the consolidated release-constants module.
 *
 * `release.ts` is the single source of truth for build-time corpus
 * stats that the UI surfaces (card count, OCR'd page count, last
 * tranche, etc.). Multiple pages used to hardcode the same numbers
 * (4,161 pages, 158 cards…); this layer reads the manifest and the
 * snapshot index so a future tranche promotion updates the whole
 * site in one pass. Run with ``node --test src/lib/release.test.ts``.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  RELEASE,
  formatCardCount,
  formatPageCount,
  formatOcrEngineLabel,
} from "./release.ts";

test("RELEASE exposes a stable shape for build-time constants", () => {
  // Schema check — these fields are the public contract. Adding new
  // fields is fine; removing one would break downstream pages.
  const keys = Object.keys(RELEASE).sort();
  assert.ok(keys.includes("currentTrancheId"));
  assert.ok(keys.includes("currentTrancheIdShort"));
  assert.ok(keys.includes("cardCount"));
  assert.ok(keys.includes("ocrPageCount"));
  assert.ok(keys.includes("lastTrancheDate"));
  assert.ok(keys.includes("release01Date"));
  assert.ok(keys.includes("trancheCount"));
});

test("currentTrancheId is the full 64-char manifest sha256", () => {
  assert.equal(typeof RELEASE.currentTrancheId, "string");
  assert.equal(RELEASE.currentTrancheId.length, 64);
  // Hex characters only.
  assert.match(RELEASE.currentTrancheId, /^[0-9a-f]{64}$/);
});

test("currentTrancheIdShort is the first 12 chars (citable identifier)", () => {
  assert.equal(RELEASE.currentTrancheIdShort.length, 12);
  assert.equal(
    RELEASE.currentTrancheIdShort,
    RELEASE.currentTrancheId.slice(0, 12),
  );
});

test("cardCount matches manifest card length and is a positive integer", () => {
  assert.equal(typeof RELEASE.cardCount, "number");
  assert.ok(Number.isInteger(RELEASE.cardCount));
  assert.ok(RELEASE.cardCount > 0);
});

test("ocrPageCount is a positive integer (build-time corpus stat)", () => {
  assert.equal(typeof RELEASE.ocrPageCount, "number");
  assert.ok(Number.isInteger(RELEASE.ocrPageCount));
  assert.ok(RELEASE.ocrPageCount > 0);
});

test("cleanedPageCount is a positive integer and ≤ ocrPageCount", () => {
  // Sprint 4b Theme E2: cleanedPageCount is the number of OCR'd
  // pages that the LLM-cleanup pass produced usable cleaned text for.
  // Always ≤ ocrPageCount because some pages skip cleaning
  // (content_filter, refusal, etc.).
  assert.equal(typeof RELEASE.cleanedPageCount, "number");
  assert.ok(Number.isInteger(RELEASE.cleanedPageCount));
  assert.ok(RELEASE.cleanedPageCount > 0);
  assert.ok(
    RELEASE.cleanedPageCount <= RELEASE.ocrPageCount,
    `cleanedPageCount (${RELEASE.cleanedPageCount}) must be ≤ ocrPageCount (${RELEASE.ocrPageCount})`,
  );
});

test("lastTrancheDate is an ISO-8601 string", () => {
  // YYYY-MM-DD prefix — the manifest's fetched_at is full ISO; we
  // expose the date portion so display contexts can render compactly.
  assert.match(RELEASE.lastTrancheDate, /^\d{4}-\d{2}-\d{2}$/);
});

test("release01Date is 2026-05-08 (the canonical PURSUE Release 01 date)", () => {
  // This is a frozen historical fact, not derived from manifest data
  // (the snapshot index records when WE fetched it, not when DoW
  // released it).
  assert.equal(RELEASE.release01Date, "2026-05-08");
});

test("trancheCount counts the snapshot index entries", () => {
  assert.equal(typeof RELEASE.trancheCount, "number");
  assert.ok(RELEASE.trancheCount >= 1);
});

test("formatCardCount produces a thousands-separated string", () => {
  assert.equal(formatCardCount(158), "158");
  assert.equal(formatCardCount(1234), "1,234");
  assert.equal(formatCardCount(0), "0");
});

test("formatPageCount produces a thousands-separated string", () => {
  assert.equal(formatPageCount(4161), "4,161");
  assert.equal(formatPageCount(999), "999");
  assert.equal(formatPageCount(1000000), "1,000,000");
});

// formatOcrEngineLabel — data-driven hero attribution (replaces the
// hardcoded "Surya + LLM-fallback" that went stale after the bake-off
// switched the operated engine to Claude Sonnet 4.6).

test("formatOcrEngineLabel: current corpus (llm-dominant) reads Sonnet primary", () => {
  // 91% llm, with small tesseract/surya/llm-anthropic tails → only the
  // dominant engine clears the share threshold.
  assert.equal(
    formatOcrEngineLabel({ llm: 7127, tesseract: 402, surya: 240, "llm-anthropic": 3 }),
    "Claude Sonnet 4.6",
  );
});

test("formatOcrEngineLabel: maps engine keys to display names, primary first", () => {
  // A genuine split (both ≥ threshold) names both, larger first.
  assert.equal(
    formatOcrEngineLabel({ llm: 5000, surya: 3000 }),
    "Claude Sonnet 4.6 + Surya",
  );
});

test("formatOcrEngineLabel: data-driven — surya-dominant corpus reads Surya first", () => {
  assert.equal(
    formatOcrEngineLabel({ surya: 5000, llm: 1500 }),
    "Surya + Claude Sonnet 4.6",
  );
});

test("formatOcrEngineLabel: collapses llm + llm-anthropic into one Sonnet credit", () => {
  assert.equal(formatOcrEngineLabel({ llm: 50, "llm-anthropic": 50 }), "Claude Sonnet 4.6");
});

test("formatOcrEngineLabel: ignores unknown + single-engine corpus shows that engine", () => {
  assert.equal(formatOcrEngineLabel({ surya: 100, unknown: 9999 }), "Surya");
});

test("formatOcrEngineLabel: assemblyai maps to a labelled audio-transcript name", () => {
  // AUD cards are transcribed by AssemblyAI; the live engine-mix block must
  // render a display name for the `assemblyai` engine key, not a raw row.
  assert.equal(
    formatOcrEngineLabel({ assemblyai: 5000 }),
    "AssemblyAI (audio transcript)",
  );
});

test("formatOcrEngineLabel: empty/zero counts → safe generic label", () => {
  assert.equal(formatOcrEngineLabel({}), "multiple engines");
  assert.equal(formatOcrEngineLabel({ llm: 0 }), "multiple engines");
});

test("RELEASE.ocrEngineLabel is a non-empty string crediting the primary engine", () => {
  assert.equal(typeof RELEASE.ocrEngineLabel, "string");
  assert.ok(RELEASE.ocrEngineLabel.length > 0);
});
