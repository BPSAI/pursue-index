/**
 * Shared row/card fixtures for the split `diff-helpers*.test.ts` suite.
 *
 * `card()` and the three duplicate-card_id row builders below are used by
 * both the pairing-engine tests (`diff-helpers-pairing.test.ts`) and the
 * field-diff tests (`diff-helpers-field-changes.test.ts`), so they live
 * here as the single source rather than as two hand-synced copies.
 *
 * This is NOT the cross-language `tests/fixtures/row_pairing_cases.json`
 * fixture — that one is read directly by `row-pairing-fixture.test.ts`
 * (TS) and `tests/unit/test_row_pairing_fixture.py` (Python) and is
 * untouched by this module.
 */

import type { CardMetadata } from "../data/types.ts";

export function card(id: string, title: string, extras: Partial<CardMetadata> = {}): CardMetadata {
  return {
    card_id: id,
    title,
    asset_type: "PDF",
    agency: "FBI",
    release_date: null,
    incident_date: null,
    incident_location: null,
    redacted: false,
    description: null,
    asset_url: null,
    asset_filename: null,
    modal_image_url: null,
    dvids_video_id: null,
    video_title: null,
    pdf_pairing: null,
    video_pairing: null,
    image_alt_text: null,
    image_virin: null,
    original_classification: null,
    featured: false,
    ...extras,
  };
}

// 9 ids in the 375-card manifest carry a PDF row plus one or more VID
// rows under the SAME card_id. Keying a Map by card_id (last row wins)
// and then diffing every curr row against that one survivor compares a
// VID row to a PDF row and fabricates field changes — "a video retitled
// into a PDF". These fixtures are built from the real duplicate ids in
// snapshot 5f5698f1 (verified against data/manifests/snapshots/).

// ea029a05470b8f4e — 1 PDF + 3 VID rows; the 3 VID rows share an
// identical (asset_url, asset_type, video_title) key and differ only by
// title (PR031 / PR032 / PR033), so they must be paired positionally.
export const EA_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d32-mission-report,-syria-october-2024.pdf";
export function ea029aRows(): CardMetadata[] {
  const vt = "Unresolved UAP Report, Syria, October 2024";
  return [
    card("ea029a05470b8f4e", "DOW-UAP-D032, Mission Report, Syria, October 2024", {
      asset_type: "PDF", asset_url: EA_URL, video_title: null, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR031, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR032, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
    card("ea029a05470b8f4e", "DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024", {
      asset_type: "VID", asset_url: EA_URL, video_title: vt, incident_location: "Syria",
    }),
  ];
}

// d8e5687dc870892d — 1 PDF + 2 VID rows (PR026 / PR027, identical key).
export const D8_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d23-mission-report-united-arab-emirates-october-2023.pdf";
export function d8e56Rows(): CardMetadata[] {
  const vt = "Unresolved UAP Report, United Arab Emirates, October 2023";
  return [
    card("d8e5687dc870892d", "DOW-UAP-D023, Mission Report, United Arab Emirates, October 2023", {
      asset_type: "PDF", asset_url: D8_URL, video_title: null, incident_location: "Arabian Gulf",
    }),
    card("d8e5687dc870892d", "DOW-UAP-PR026, Unresolved UAP Report, United Arab Emirates, October 2023", {
      asset_type: "VID", asset_url: D8_URL, video_title: vt, incident_location: "United Arab Emirates",
    }),
    card("d8e5687dc870892d", "DOW-UAP-PR027, Unresolved UAP Report, United Arab Emirates, October 2023", {
      asset_type: "VID", asset_url: D8_URL, video_title: vt, incident_location: "United Arab Emirates",
    }),
  ];
}

// c1c59236394f7b14 — the 2-row shape: 1 PDF + 1 VID. Live, the buggy
// map diffed this id's VID row against its PDF row and asserted title,
// asset_type, incident_date, incident_location and description all
// changed — the exact regression this task fixes.
export const C1_URL =
  "https://www.war.gov/medialink/ufo/release_1/dow-uap-d10-mission-report-middle-east-may-2022.pdf";
export function c1c59Rows(): CardMetadata[] {
  return [
    card("c1c59236394f7b14", "DOW-UAP-D010, Mission Report, Middle East, May 2022", {
      asset_type: "PDF", asset_url: C1_URL, video_title: null, incident_location: "Iraq",
    }),
    card("c1c59236394f7b14", "DOW-UAP-PR019, Unresolved UAP Report, Middle East, May 2022", {
      asset_type: "VID", asset_url: C1_URL,
      video_title: "Unresolved UAP Report, Middle East, May 2022", incident_location: "Middle East",
    }),
  ];
}
