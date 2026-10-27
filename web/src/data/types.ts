// Mirror of pursue_index.scrape.types — keep in sync with the Python side.

export type AssetType = "PDF" | "VID" | "IMG" | "AUD";

export interface CardMetadata {
  card_id: string;
  title: string;
  asset_type: AssetType;
  agency: string;
  release_date: string | null;
  incident_date: string | null;
  incident_location: string | null;
  redacted: boolean;
  // Upstream "feature this card" flag (added in tranche a62a76884e52,
  // 2026-06-10 — the CSV's leading "Featured" column). Snapshots taken
  // before the column lack this field; treat its absence as false.
  featured?: boolean;
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
  // NOTE: the Python `CardMetadata` ships a `raw` dict holding upstream CSV
  // columns the scraper does not map (currently 12 blank `ColumnN` headers,
  // so every value is an empty string). No UI consumer reads it, and the
  // cards summary drops it. Omitting it here keeps the typed-bundle shape
  // lean. The Python side already enforces `extra="forbid"` on the manifest
  // schema, so
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
//   - "metadata-only-resave" — auto-rename: new bytes = old bytes + a
//                         metadata-only PDF update (tranche_diff --bytes-dir)
//   - "operator_manual" — Class C operator-approved rename
//   - "operator_revoke" — tombstone removing a prior alias
// Optional byte-change evidence (R7C.13), present only where a byte
// verdict is actually known; rows without it render as before:
//   - `old_byte_sha256` / `new_byte_sha256` — sha256 of the bytes on each side
//   - `change_nature`:
//       "metadata-only"   — new bytes = old bytes + a metadata-only PDF update
//       "content-changed" — the document content itself differs
//       "unknown"         — bytes recorded, nature not established
export interface AliasEntry {
  old_card_id: string;
  new_card_id: string;
  method: "byte_collision" | "operator_manual" | "operator_revoke" | string;
  established: string;
  tranche_sha256?: string;
  old_byte_sha256?: string;
  new_byte_sha256?: string;
  change_nature?: "metadata-only" | "content-changed" | "unknown" | string;
}

export interface PageRecord {
  card_id: string;
  page: number;
  text: string;
  confidence: number;
  engine: string;
}
