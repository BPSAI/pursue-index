/**
 * Pure helpers for the /timeline page.
 *
 * Builds per-card date entries by combining the manifest (card metadata),
 * curated display_dates.json (operator-approved), and
 * display_dates_proposals.jsonl (agent drafts shown as tentative ghosts).
 *
 * Date shapes the corpus carries:
 *   "YYYY-MM-DD"        → point date
 *   "YYYY-MM"           → month precision (plotted at mid-month)
 *   "YYYY"              → year precision (plotted at mid-year)
 *   {range: [a, b]}     → coverage range
 *   null + abstention   → bucketed in "undated"
 */

import type { CardMetadata } from "../data/types.ts";

export type DateSource = "approved" | "proposal" | "none";

export interface DateEntry {
  card_id: string;
  display_date: string | null;
  display_date_range: [string, string] | null;
  display_date_evidence?: string | null;
  display_date_abstention?: string | null;
  display_date_curator?: string | null;
}

export interface TimelineCard {
  card: CardMetadata;
  source: DateSource;
  // Resolved numeric position on the year axis when known; null when abstained.
  yearPos: number | null;
  // Precision so the UI can render markers differently (day-level dot vs
  // year-level band).
  precision: "day" | "month" | "year" | "range" | "none";
  // Raw fields preserved for tooltip rendering.
  display_date: string | null;
  display_date_range: [string, string] | null;
  evidence: string | null;
  abstention: string | null;
  curator: string | null;
}

/**
 * Parse a "YYYY-MM-DD" or "YYYY-MM" or "YYYY" string into a numeric
 * year position (e.g. 1947-07-08 → 1947.515 for mid-July). Returns
 * null when unparseable.
 */
export function dateToYearPos(s: string | null | undefined): number | null {
  if (!s) return null;
  const m = String(s).match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/);
  if (!m) return null;
  const year = parseInt(m[1], 10);
  const month = m[2] ? parseInt(m[2], 10) : null;
  const day = m[3] ? parseInt(m[3], 10) : null;
  if (Number.isNaN(year)) return null;
  if (month == null) return year + 0.5; // mid-year
  // months 1-12 → 0-11/12 fraction. Default day = 15 (mid-month).
  const d = day ?? 15;
  // 30-day approximation is fine for plotting.
  return year + (month - 1) / 12 + (d - 1) / 365;
}

export function detectPrecision(entry: DateEntry): TimelineCard["precision"] {
  if (entry.display_date_range) return "range";
  const s = entry.display_date;
  if (!s) return "none";
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return "day";
  if (/^\d{4}-\d{2}$/.test(s)) return "month";
  if (/^\d{4}$/.test(s)) return "year";
  return "none";
}

/**
 * Build the full timeline-card view from the three data sources:
 *   - cards    : the manifest's cards array
 *   - approved : indexed by card_id, operator-curated entries
 *   - proposals: indexed by card_id, agent-drafted entries (used when
 *                approved is missing for that card)
 *
 * Approved beats proposal beats none. The returned list is in manifest
 * order; downstream consumers can sort/group as needed.
 */
export function buildTimelineCards(
  cards: CardMetadata[],
  approved: Record<string, DateEntry>,
  proposals: Record<string, DateEntry>,
): TimelineCard[] {
  return cards.map((card) => {
    const a = approved[card.card_id];
    const p = proposals[card.card_id];
    const entry: DateEntry | null = a ?? p ?? null;
    const source: DateSource = a ? "approved" : p ? "proposal" : "none";
    if (!entry) {
      return {
        card,
        source,
        yearPos: null,
        precision: "none",
        display_date: null,
        display_date_range: null,
        evidence: null,
        abstention: null,
        curator: null,
      };
    }
    const precision = detectPrecision(entry);
    let yearPos: number | null = null;
    if (precision === "range" && entry.display_date_range) {
      yearPos = dateToYearPos(entry.display_date_range[0]);
    } else {
      yearPos = dateToYearPos(entry.display_date);
    }
    return {
      card,
      source,
      yearPos,
      precision,
      display_date: entry.display_date ?? null,
      display_date_range: entry.display_date_range ?? null,
      evidence: entry.display_date_evidence ?? null,
      abstention: entry.display_date_abstention ?? null,
      curator: entry.display_date_curator ?? null,
    };
  });
}

/**
 * Compute the [min, max] year span across a timeline-card list,
 * padded to whole years for axis rendering. Returns null when no
 * card has a date.
 */
export function yearSpan(items: TimelineCard[]): [number, number] | null {
  const yrs = items
    .map((it) => it.yearPos)
    .filter((y): y is number => y !== null);
  if (yrs.length === 0) return null;
  const min = Math.floor(Math.min(...yrs));
  const max = Math.ceil(Math.max(...yrs));
  return [min, max];
}

/**
 * Counts by source for the page header readout.
 */
export function summary(items: TimelineCard[]): {
  total: number;
  approved: number;
  proposal: number;
  abstained: number;
  undated: number;
} {
  let approved = 0,
    proposal = 0,
    abstained = 0,
    undated = 0;
  for (const it of items) {
    if (it.source === "approved") approved++;
    else if (it.source === "proposal") proposal++;
    if (it.precision === "none") {
      if (it.abstention) abstained++;
      else undated++;
    }
  }
  return {
    total: items.length,
    approved,
    proposal,
    abstained,
    undated,
  };
}
