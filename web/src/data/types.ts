// Mirror of pursue_index.scrape.types — keep in sync with the Python side.

export type AssetType = "PDF" | "VID" | "IMG";

export interface CardMetadata {
  card_id: string;
  title: string;
  asset_type: AssetType;
  agency: string;
  release_date: string | null;
  incident_date: string | null;
  incident_location: string | null;
  redacted: boolean;
  description: string | null;
  asset_url: string | null;
  asset_filename: string | null;
  modal_image_url: string | null;
  dvids_video_id: string | null;
  video_title: string | null;
  pdf_pairing: string | null;
  video_pairing: string | null;
  // Upstream accessibility metadata (added in tranche c9cc83fcaf43,
  // 2026-05-14). Section 508 alt-text + DoDI 5040.02 VIRIN. Not every
  // card has them — fall back to title-based alts when absent.
  image_alt_text: string | null;
  image_virin: string | null;
  // Extracted from `image_alt_text` at parse time when an explicit
  // classification keyword is present. Values: "Top Secret" | "Secret" |
  // "Confidential" | "Restricted" | "Unclassified" | null. ~13% of cards
  // have one; the rest say "Declassified" without a level.
  original_classification: string | null;
  // NOTE: the Python `CardMetadata` ships a `raw` dict for forward-compat
  // with future CSV columns, but it's always empty in the manifest we
  // build. Dropping it here keeps the typed-bundle shape lean. The Python
  // side already enforces `extra="forbid"` on the manifest schema, so
  // downstream loaders don't depend on this field existing on the wire.
}

export interface Manifest {
  source_url: string;
  fetched_at: string;
  csv_sha256: string;
  cards: CardMetadata[];
}

// Mirror of one row in `data/card-aliases.json`. The `aliases` array
// in that file is consumed by the /diff page (rename-aware grouping)
// AND by the worker's redirect lane. `method`:
//   - "byte_collision"  — Class A auto-rename (new card_id maps to same byte sha)
//   - "operator_manual" — Class C operator-approved rename
//   - "operator_revoke" — tombstone removing a prior alias
export interface AliasEntry {
  old_card_id: string;
  new_card_id: string;
  method: "byte_collision" | "operator_manual" | "operator_revoke" | string;
  established: string;
  tranche_sha256?: string;
}

export interface PageRecord {
  card_id: string;
  page: number;
  text: string;
  confidence: number;
  engine: string;
}

// Novelty / disclosure-status types — mirrors the Python
// `pursue_index.novelty.aggregate.CardNovelty` shape, flattened to the
// compact map `scripts/build_novelty_data.py` writes for the browser.

export type DisclosureStatus = "novel" | "partial" | "previously-disclosed";

export interface NoveltyMatch {
  page: number;
  ref_archive: string;
  ref_card_id?: string;
  ref_page?: number;
  similarity: number;
}

export interface CardNovelty {
  disclosure_status: DisclosureStatus;
  novelty_score: number;
  matches: NoveltyMatch[];
}

export interface NoveltyPayload {
  archive_id: string;
  computed_at: string;
  thresholds: { high: number; partial: number };
  cards: Record<string, CardNovelty>;
}
