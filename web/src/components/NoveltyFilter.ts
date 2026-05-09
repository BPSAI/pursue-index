// Helpers for the disclosure-status filter chip used in CardExplorer.
//
// The novelty payload is loaded once on hydrate from /data/novelty.json.
// If the fetch fails (404, malformed JSON), the filter dropdown disables
// and the per-card pill doesn't render. The UI degrades gracefully to
// "novelty comparison pending."

import type { CardNovelty, DisclosureStatus, NoveltyPayload } from "../data/types";

export type DisclosureFilter = "" | DisclosureStatus;

export interface NoveltyState {
  loaded: boolean;
  available: boolean; // true iff payload was fetched + parsed
  archiveId: string;
  thresholds: { high: number; partial: number };
  cards: Record<string, CardNovelty>;
}

export const EMPTY_NOVELTY: NoveltyState = {
  loaded: false,
  available: false,
  archiveId: "",
  thresholds: { high: 0.85, partial: 0.7 },
  cards: {},
};

/** Pill colors mirror the existing TYPE_TONE palette in CardExplorer. */
export const DISCLOSURE_TONE: Record<
  DisclosureStatus,
  { fg: string; bg: string; border: string; label: string }
> = {
  novel: {
    fg: "text-[color:var(--color-signal-green)]",
    bg: "bg-[color:var(--color-signal-green)]/10",
    border: "border-[color:var(--color-signal-green)]/40",
    label: "NOVEL",
  },
  partial: {
    fg: "text-[color:var(--color-signal-amber)]",
    bg: "bg-[color:var(--color-signal-amber)]/10",
    border: "border-[color:var(--color-signal-amber)]/40",
    label: "PARTIAL",
  },
  "previously-disclosed": {
    fg: "text-[color:var(--color-signal-cyan)]",
    bg: "bg-[color:var(--color-signal-cyan)]/10",
    border: "border-[color:var(--color-signal-cyan)]/40",
    label: "PREVIOUSLY DISCLOSED",
  },
};

/** Fetch the static novelty payload. Resolves to EMPTY_NOVELTY on any error. */
export async function loadNovelty(base: string): Promise<NoveltyState> {
  try {
    const res = await fetch(`${base}/data/novelty.json`, { cache: "force-cache" });
    if (!res.ok) return { ...EMPTY_NOVELTY, loaded: true };
    const payload = (await res.json()) as NoveltyPayload;
    return {
      loaded: true,
      available: true,
      archiveId: payload.archive_id ?? "",
      thresholds: payload.thresholds ?? { high: 0.85, partial: 0.7 },
      cards: payload.cards ?? {},
    };
  } catch {
    return { ...EMPTY_NOVELTY, loaded: true };
  }
}

/** Apply the disclosure filter against the loaded novelty state. */
export function passesDisclosureFilter(
  cardId: string,
  filter: DisclosureFilter,
  novelty: NoveltyState,
): boolean {
  if (!filter) return true;
  if (!novelty.available) return true; // filter is no-op when payload is absent
  return novelty.cards[cardId]?.disclosure_status === filter;
}
