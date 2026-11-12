/**
 * Pure helpers for the GalleryIsland, split out so they are testable
 * without rendering the island. Run the tests with ``node --test
 * src/components/gallery-helpers.test.ts``.
 */

import type { CardMetadata } from "../data/types";

/** A full 19xx/20xx year, not part of a longer digit run. */
const FULL_YEAR_RE = /(?<!\d)(?:19|20)\d{2}(?!\d)/;
/** Numeric M/D/YYYY dates, capturing the four-digit year. */
const SLASH_YYYY_RE = /\b\d{1,2}\/\d{1,2}\/(\d{4})\b/g;

/**
 * True when ``s`` carries a numeric M/D/YYYY date whose year is not a
 * 19xx/20xx year (e.g. an upstream "5/24/2962"). Such a value is not
 * read for a year at all, rather than having a fragment of it guessed.
 */
function hasImplausibleSlashYear(s: string): boolean {
  for (const m of s.matchAll(SLASH_YYYY_RE)) {
    if (!FULL_YEAR_RE.test(m[1])) return true;
  }
  return false;
}

/**
 * Year-bucket label for the tile's date stamp. Prefers the curated
 * `display_date` (from data/display_dates.json, attached by the gallery
 * page), then `incident_date` (when present and parseable), then
 * `release_date`. The manifest fields are free-form strings like
 * "5/8/26", "5/8/2026" or "Late 2025" so a strict Date parse would
 * refuse most of them; we extract a 4-digit year or a 2-digit year with
 * a 19xx/20xx heuristic instead.
 */
export function tileYear(
  c: Pick<CardMetadata, "incident_date" | "release_date" | "display_date">,
): string {
  const sources = [c.display_date, c.incident_date, c.release_date].filter(Boolean) as string[];
  for (const s of sources) {
    if (hasImplausibleSlashYear(s)) continue;
    // 4-digit year
    const m4 = s.match(FULL_YEAR_RE);
    if (m4) return m4[0];
    // 2-digit year — pick up "26" → 2026, "47" → 1947, etc.
    const m2 = s.match(/\b(\d{2})\b/g);
    if (m2 && m2.length) {
      const last = m2[m2.length - 1];
      const n = parseInt(last, 10);
      if (!Number.isNaN(n)) {
        return n < 50 ? `20${last}` : `19${last}`;
      }
    }
  }
  return "—";
}

/**
 * Attach each card's curated `display_date` from the display-date
 * overlay (the same `data/display_dates.json` the card page reads).
 * Cards without an overlay row, or whose row is an abstention, pass
 * through unchanged.
 */
export function withDisplayDates<T extends { card_id: string }>(
  cards: readonly T[],
  entries: readonly { card_id: string; display_date?: string | null }[],
): (T & { display_date?: string | null })[] {
  const byId = new Map<string, string>();
  for (const e of entries) {
    if (e.card_id && e.display_date) byId.set(e.card_id, e.display_date);
  }
  return cards.map((c) => {
    const d = byId.get(c.card_id);
    return d ? { ...c, display_date: d } : c;
  });
}
