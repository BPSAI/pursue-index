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

export interface PageRecord {
  card_id: string;
  page: number;
  text: string;
  confidence: number;
  engine: string;
}
