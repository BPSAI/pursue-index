// Display treatment for `pdf_pairing` / `video_pairing` values on the
// card-detail page (web/src/pages/card/[card_id].astro) and the
// collection filter on the homepage (CardExplorer.tsx).
//
// Upstream writes two shapes into these fields: an explicit document
// reference (e.g. "DOW-UAP-D176") or, since tranche 096ef2c0058a, a
// collection tag ("TAG:AAWSAP"). Operator ruling on #179: render a
// `TAG:<name>` value as a labelled collection chip linking to the card
// list filtered to that tag, rather than the literal `TAG:AAWSAP`
// string. The raw value is always preserved (`raw` below) so the
// archive-fidelity property holds regardless of display treatment.

export const TAG_PREFIX = "TAG:";

export interface TagPairingDisplay {
  kind: "tag";
  label: string;
  raw: string;
  tag: string;
  chipText: string;
  href: string;
}

export interface VerbatimPairingDisplay {
  kind: "verbatim";
  label: string;
  raw: string;
}

export type PairingDisplay = TagPairingDisplay | VerbatimPairingDisplay;

/**
 * Classify a single pairing value for display. `base` is the site's
 * BASE_URL (e.g. "" or "/pursue") and is used to build the collection
 * chip's link to the homepage's hash-based `tag` filter.
 */
export function pairingDisplay(
  label: string,
  value: string,
  base: string,
): PairingDisplay {
  if (value.startsWith(TAG_PREFIX)) {
    const tag = value.slice(TAG_PREFIX.length);
    return {
      kind: "tag",
      label,
      raw: value,
      tag,
      chipText: `${tag} collection`,
      href: `${base}/#tag=${encodeURIComponent(tag)}`,
    };
  }
  return { kind: "verbatim", label, raw: value };
}

/** Subset of CardMetadata this module's filter needs. */
export interface TagPairingCard {
  card_id: string;
  pdf_pairing: string | null;
  video_pairing: string | null;
}

/** Does this card carry the given collection tag on either pairing field? */
export function cardHasTag<T extends TagPairingCard>(
  card: T,
  tag: string,
): boolean {
  const want = `${TAG_PREFIX}${tag}`;
  return card.pdf_pairing === want || card.video_pairing === want;
}

/** All cards carrying the given collection tag, order preserved. */
export function cardsInTagCollection<T extends TagPairingCard>(
  cards: T[],
  tag: string,
): T[] {
  return cards.filter((c) => cardHasTag(c, tag));
}
