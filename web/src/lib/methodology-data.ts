/**
 * Build-time inputs for the /methodology page.
 *
 * Every figure that page states about the corpus is derived here, from the
 * data committed in this repo, at build time. Nothing falls back to a
 * remembered number: this is a static build, so a fallback would ship a
 * claim about the corpus that no data produced. Each reader throws when it
 * cannot read its input, which fails the build instead.
 *
 * Path candidates are passed in because Astro resolves this module from two
 * different working directories (the dev server's and the build's).
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

/** One reason the cleanup pass skipped a page, with how many pages it covers. */
export interface SkipCause {
  cause: string;
  count: number;
}

export interface CleanupStats {
  /** Cards represented in the cleanup pass. */
  cardsWithCleaned: number;
  /** Pages the cleanup pass looked at. */
  totalPagesInCleanupPass: number;
  /** Pages it produced cleaned text for. */
  totalCleanedPages: number;
  /** Pages it left as raw OCR. */
  skippedPages: number;
  /** Why those pages were skipped, largest cause first. */
  skipCauses: SkipCause[];
}

interface CleanedPage {
  card_id?: string;
  text?: string;
  cleanup_skipped?: string;
}

function firstExisting(candidates: string[], what: string): string {
  for (const path of candidates) {
    if (existsSync(path)) return path;
  }
  throw new Error(
    `${what} not found — looked in: ${candidates.join(", ")}. ` +
      "The methodology page derives its figures from this file at build time.",
  );
}

function readJson<T>(path: string, what: string): T {
  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch (err) {
    throw new Error(`${what} could not be read from ${path}: ${String(err)}`);
  }
}

/** Cleanup-pass coverage and skip causes, from `pages-cleaned.json`. */
export function readCleanupStats(candidates: string[]): CleanupStats {
  const path = firstExisting(candidates, "pages-cleaned.json");
  const data = readJson<{ pages?: CleanedPage[] }>(path, "pages-cleaned.json");
  if (!Array.isArray(data.pages)) {
    throw new Error(`pages-cleaned.json at ${path} has no pages array`);
  }

  const cards = new Set<string>();
  const causes = new Map<string, number>();
  let cleaned = 0;
  for (const page of data.pages) {
    if (page.card_id) cards.add(page.card_id);
    const hasText = typeof page.text === "string" && page.text.length > 0;
    if (hasText) {
      cleaned += 1;
      continue;
    }
    const cause = page.cleanup_skipped || "unrecorded";
    causes.set(cause, (causes.get(cause) ?? 0) + 1);
  }

  return {
    cardsWithCleaned: cards.size,
    totalPagesInCleanupPass: data.pages.length,
    totalCleanedPages: cleaned,
    skippedPages: data.pages.length - cleaned,
    skipCauses: [...causes.entries()]
      .map(([cause, count]) => ({ cause, count }))
      .sort((a, b) => b.count - a.count || a.cause.localeCompare(b.cause)),
  };
}

export interface SidecarModelBreakdown {
  modelCounts: Record<string, number>;
  /** Sidecars counted — by construction, the sum of `modelCounts`. */
  total: number;
}

/**
 * Per-model split of the image-observation sidecars.
 *
 * A file is a sidecar only if it records the model that produced the pass;
 * the directory's `index.json` does not, and counting it made the stated
 * total disagree with the split printed beside it.
 */
export function readSidecarModelBreakdown(candidates: string[]): SidecarModelBreakdown {
  const dir = firstExisting(candidates, "image-observation sidecar directory");
  const modelCounts: Record<string, number> = {};
  let total = 0;
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
    const data = readJson<{ our_pass?: { model?: string } }>(
      resolve(dir, file),
      `image-observation sidecar ${file}`,
    );
    const model = data.our_pass?.model;
    if (!model) continue;
    modelCounts[model] = (modelCounts[model] ?? 0) + 1;
    total += 1;
  }
  if (total === 0) {
    throw new Error(`no image-observation sidecars with a recorded model in ${dir}`);
  }
  return { modelCounts, total };
}

/** Distinct cards carrying at least one OCR'd page, from `pages.json`. */
export function countOcrCards(candidates: string[]): number {
  const path = firstExisting(candidates, "pages.json");
  const rows = readJson<Array<{ card_id?: string; text?: string }>>(path, "pages.json");
  if (!Array.isArray(rows)) throw new Error(`pages.json at ${path} is not an array`);
  const cards = new Set<string>();
  for (const row of rows) {
    if (row?.card_id && typeof row.text === "string" && row.text.length > 0) {
      cards.add(row.card_id);
    }
  }
  return cards.size;
}

/**
 * State of the re-OCR migration off Surya, phrased from the live page
 * counts rather than from a remembered stage of the work.
 */
export function describeSuryaMigration(suryaPages: number): string {
  if (suryaPages <= 0) {
    return (
      "The re-OCR migration is complete: no surya-tagged pages remain in the " +
      "corpus. The retired Surya adapter stays in the repo " +
      "(`pursue ocr run --engine surya`) for reproducibility only."
    );
  }
  return (
    `${suryaPages.toLocaleString()} pages are still tagged surya, from ` +
    "Release-01 extractions predating the migration. The retired Surya " +
    "adapter stays in the repo (`pursue ocr run --engine surya`) for " +
    "reproducibility only."
  );
}
