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

/**
 * Inline qualifier rendered alongside every disclosure-status chip at
 * v1.0.0 launch. Honest framing: the reference corpus is a small
 * synthetic placeholder, NOT a real prior-disclosure archive. When
 * Black Vault integration lands, callers can swap this constant (or
 * pass `archiveId` to `disclosurePillLabel`) to update every chip on
 * the site in one place.
 */
export const CORPUS_QUALIFIER = "(against preview corpus)";

/**
 * Map a manifest `archive_id` to the short tag we stamp onto chips as
 * `data-corpus="..."`. The synthetic-placeholder corpus (and the
 * empty/absent case) maps to `"preview"` so the chip's `data-corpus`
 * attribute is stable user-facing-copy regardless of internal naming.
 */
export function corpusTag(archiveId: string | undefined): string {
  if (!archiveId || archiveId === "synthetic-placeholder") return "preview";
  return archiveId;
}

/**
 * Resolve the qualifier text for a given reference corpus. Defaults
 * to the preview-corpus wording. A future Black Vault swap is a
 * one-line change here, not a sweep across components.
 */
function qualifierFor(archiveId: string | undefined): string {
  const tag = corpusTag(archiveId);
  if (tag === "blackvault") return "(against Black Vault reference)";
  return CORPUS_QUALIFIER;
}

/**
 * Build the structured label for a disclosure chip: the bold status
 * word + the de-emphasized parenthetical naming the reference corpus.
 * Returning a structured object (rather than a pre-formatted string)
 * lets the renderer style the two parts differently — the qualifier
 * is rendered smaller and dimmer than the status.
 */
export function disclosurePillLabel(
  status: DisclosureStatus,
  archiveId?: string,
): { status: string; qualifier: string } {
  return {
    status: DISCLOSURE_TONE[status].label,
    qualifier: qualifierFor(archiveId),
  };
}

/** Fetch the static novelty payload. Resolves to EMPTY_NOVELTY on any error.
 *
 * `available` is true ONLY when a real reference corpus is loaded. The
 * synthetic-placeholder corpus loads cards + archiveId so the Provenance
 * panel on the card detail page can render its honest "placeholder; full
 * comparison pending" message — but the index page's per-card pills and
 * filter dropdown are gated on `available`, so they hide entirely until
 * a real reference corpus (Black Vault et al.) lands. Showing a "NOVEL"
 * pill on every card when the comparison is against 10 placeholder
 * passages misleads readers into thinking we measured something we didn't.
 */
export async function loadNovelty(base: string): Promise<NoveltyState> {
  try {
    const res = await fetch(`${base}/data/novelty.json`, { cache: "force-cache" });
    if (!res.ok) return { ...EMPTY_NOVELTY, loaded: true };
    const payload = (await res.json()) as NoveltyPayload;
    const archiveId = payload.archive_id ?? "";
    const isPlaceholder = archiveId === "synthetic-placeholder" || archiveId === "";
    return {
      loaded: true,
      available: !isPlaceholder,
      archiveId,
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
