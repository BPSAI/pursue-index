# Tranche diff — `c3f8209ef5f5…`

Prior manifest sha: `19e6dd7a69d5…`

## Summary

- **0** confirmed renames (Class A — safe to alias)
- **0** net-new content (Class B — ingest normally)
- **4** quarantined (Class C — manual review required)
- **0** restorations with byte-identical content (safe)
- **0** restorations with MODIFIED content (manual review required — possible tampering)
- **0** restorations with unknown bytes (no asset_url to verify)
- **1** removed upstream (no rename match)
- **4** field-only changes on existing cards
- **0** existing cards with a row added or withdrawn

## Renames confirmed (Class A — safe to alias)

_None._

## Net-new content (Class B — ingest normally)

_None._

## Quarantined (Class C — MANUAL REVIEW REQUIRED)

### `247e6e1bd6da7377` — LLE-UAP-D002, Transcript of an Unresolved UAP Report, Colorado, October 2023
- new byte_sha256: `07ab7c9a8dc590ddf2f97be9…`
- new asset_filename: `LLE-UAP-D002_Transcript-of-an-Unresolved-UAP-Report-Colorado-October-2023.pdf`
- candidate matches (ranked by signal strength — more reasons firing = stronger):
  - ★★ `649f0e15f268915e` — LLE-UAP-PR004, Unresolved UAP Report, Colorado, October 2023 — _same agency + same incident_date (October, 2023); same incident_location (Colorado)_

### `31656bd3e7de783d` — LLE-UAP-D003, Transcript of an Unresolved UAP Report, Colorado, October 2023
- new byte_sha256: `3fb6a932507382c052bb4c14…`
- new asset_filename: `LLE-UAP-D003_Transcript-of-an-Unresolved-UAP-Report-Colorado-October-2023.pdf`
- candidate matches (ranked by signal strength — more reasons firing = stronger):
  - ★★ `649f0e15f268915e` — LLE-UAP-PR004, Unresolved UAP Report, Colorado, October 2023 — _same agency + same incident_date (October, 2023); same incident_location (Colorado)_

### `b1d24cb7f46cfa20` — LLE-UAP-D004, Transcript of an Unresolved UAP Report, Colorado, January 2024
- new byte_sha256: `458d5cf945dfcb12b9e91814…`
- new asset_filename: `LLE-UAP-D004_Transcript-of-an-Unresolved-UAP-Report-Colorado-January-2024.pdf`
- candidate matches (ranked by signal strength — more reasons firing = stronger):
  - ★★ `649f0e15f268915e` — LLE-UAP-PR004, Unresolved UAP Report, Colorado, October 2023 — _same incident_location (Colorado); matching numeric id 4_

### `cb8be77a22e07f9b` — LLE-UAP-PR004, Unresolved UAP Report, Colorado, January 2024
- new byte_sha256: `unknown…`
- new asset_filename: ``
- candidate matches (ranked by signal strength — more reasons firing = stronger):
  - ★★★ `649f0e15f268915e` — LLE-UAP-PR004, Unresolved UAP Report, Colorado, October 2023 — _same agency + same incident_date (October, 2023); same incident_location (Colorado); matching numeric id 4_

## Restored — byte-identical to previously preserved (safe)

_None._

## Restored — MODIFIED bytes (POSSIBLE TAMPERING — MANUAL REVIEW REQUIRED)

_None._

## Restored — bytes unknown (no asset_url to verify)

_None._

## Removed upstream (candidates for /removed — or candidate rename sources)

_An old card_id can appear here AND in the Quarantined section's 'candidate matches' list — that's by design while operator review is pending. Once you `--approve-rename <new>=<old>`, that pairing materializes as an alias and the old card_id is no longer a candidate for /removed. The 'candidate rename source for' column shows the reverse view: which quarantined cards (if any) are hypothesized to be this old card's new identity._

| card_id | title | filename | candidate rename source for |
|---|---|---|---|
| `649f0e15f268915e` | LLE-UAP-PR004, Unresolved UAP Report, Colorado, October 2023 | `` | ★★★ `cb8be77a22e07f9b`<br>★★ `247e6e1bd6da7377`<br>★★ `31656bd3e7de783d`<br>★★ `b1d24cb7f46cfa20` |

## Field-only changes (same card_id, different metadata)

### `1b33dafd36c74c06`
- **pdf_pairing**: `None` → `LLE-UAP-D001`

### `78236aa834b34246`
- **pdf_pairing**: `None` → `LLE-UAP-D002`

### `88443d8d0c5b0c44`
- **description**: `This document is a transcript from a UAP sighting by local l` → `This document is a transcript of a 1-minute, 19-second video`
- **image_alt_text**: `Transcript Document` → `Transcript Document.`
- **image_virin**: `260918-D-D0360-1146` → `260918-O-D0360-1165`
- **video_pairing**: `LLE-UAP-PR004` → `LLE-UAP-PR001`

### `f55d5c010b11b301`
- **pdf_pairing**: `None` → `LLE-UAP-D003`

## Row-level changes (same card_id, a row added or withdrawn)

_None._
