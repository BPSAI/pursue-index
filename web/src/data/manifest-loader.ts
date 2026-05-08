import type { Manifest, CardMetadata } from "./types";
import raw from "./manifest.json";

export const manifest: Manifest = raw as Manifest;

export const cards: CardMetadata[] = manifest.cards;

export function uniqueValues<K extends keyof CardMetadata>(
  key: K,
): Array<NonNullable<CardMetadata[K]>> {
  const seen = new Set<NonNullable<CardMetadata[K]>>();
  for (const c of cards) {
    const v = c[key];
    if (v != null) seen.add(v as NonNullable<CardMetadata[K]>);
  }
  return Array.from(seen).sort();
}

export function cardById(id: string): CardMetadata | undefined {
  return cards.find((c) => c.card_id === id);
}

export function summary() {
  const byAgency: Record<string, number> = {};
  const byType: Record<string, number> = {};
  let redactedCount = 0;
  for (const c of cards) {
    byAgency[c.agency] = (byAgency[c.agency] ?? 0) + 1;
    byType[c.asset_type] = (byType[c.asset_type] ?? 0) + 1;
    if (c.redacted) redactedCount++;
  }
  return {
    total: cards.length,
    byAgency,
    byType,
    redacted: redactedCount,
    fetchedAt: manifest.fetched_at,
    csvSha256: manifest.csv_sha256,
  };
}
