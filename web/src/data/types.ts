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
  raw: Record<string, string>;
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
