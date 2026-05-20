// Pure helpers for `web/src/pages/altered.astro`. Extracted out of the
// page module so the row-building, sorting, and current-vs-oldest
// assumptions can be tested independently of Astro SSR.

export interface ByteHistoryEntry {
  byte_sha256: string;
  byte_size: number;
  fetched_at: string;
  archive_key: string;
  asset_filename: string | null;
  is_current: boolean;
}

export interface CardLookup {
  card_id: string;
  title: string;
  asset_type: string;
}

export interface AlteredRow {
  card_id: string;
  title: string;
  asset_type: string;
  current_entry: ByteHistoryEntry;
  oldest_entry: ByteHistoryEntry;
  total_versions: number;
}

/**
 * Build the /altered table rows from the byte-history map + the active
 * manifest's cards.
 *
 * Contract pinned by the co-located tests:
 *
 * * Cards whose card_id isn't in the active manifest (i.e., they were
 *   removed entirely, covered by /removed) are skipped.
 * * For each retained card, ``current_entry`` is ``entries[0]`` and
 *   ``oldest_entry`` is ``entries[entries.length - 1]``. The
 *   build_byte_history script's contract is "newest-first" so index
 *   0 is the current pointer and the last index is the oldest preserved
 *   version. The /altered table relies on this ordering.
 * * Rows sort by ``current_entry.fetched_at`` descending (most-recent
 *   edit first), tie-broken by ``title`` ascending.
 *
 * Pure: no I/O, no Astro deps.
 */
export function buildAlteredRows(
  byteHistory: Record<string, ByteHistoryEntry[]>,
  cards: CardLookup[],
): AlteredRow[] {
  const cardsById = new Map(cards.map((c) => [c.card_id, c]));
  const rows: AlteredRow[] = [];
  for (const [cardId, entries] of Object.entries(byteHistory)) {
    const card = cardsById.get(cardId);
    if (!card) continue;
    if (entries.length < 2) continue;
    rows.push({
      card_id: cardId,
      title: card.title,
      asset_type: card.asset_type,
      current_entry: entries[0],
      oldest_entry: entries[entries.length - 1],
      total_versions: entries.length,
    });
  }
  // Comparator returns 0 only when both keys (fetched_at + title) are
  // equal — title's localeCompare returns 0 for identical strings, so
  // the chained return is contract-compliant. (Codex P2 / PR #71
  // fix-pass: paired with build_byte_history.mjs's comparator.)
  rows.sort((a, b) => {
    const ad = a.current_entry.fetched_at;
    const bd = b.current_entry.fetched_at;
    if (ad !== bd) return ad < bd ? 1 : -1;
    return a.title.localeCompare(b.title);
  });
  return rows;
}
