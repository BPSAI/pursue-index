# Tranche diff — `65572b38d27c…`

Prior manifest sha: `0d7e9ba1d51c…`

## Summary

- **0** confirmed renames (Class A — safe to alias)
- **0** net-new content (Class B — ingest normally)
- **16** quarantined (Class C — manual review required)
- **1** restorations with byte-identical content (safe)
- **0** restorations with MODIFIED content (manual review required — possible tampering)
- **0** restorations with unknown bytes (no asset_url to verify)
- **17** removed upstream (no rename match)
- **93** field-only changes on existing cards

## Renames confirmed (Class A — safe to alias)

_None._

## Net-new content (Class B — ingest normally)

_None._

## Quarantined (Class C — MANUAL REVIEW REQUIRED)

### `0499d6dc86c848d6` — DOW-UAP-PR040, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: same incident_location (Arabian Gulf); matching numeric id 40

### `167f6a21c7238d0c` — NASA-UAP-D003A, Gemini 7 Audio Excerpt, 1965
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `4b346a44f42f6a05`
- reasons: same agency + same incident_date (12/5/65); same incident_location (Low Earth Orbit)

### `2b6de60628336eb8` — DOW-UAP-PR045, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `f62bdd9d2cd17b38`
- reasons: matching numeric id 45; same incident_location (Southern United States)

### `42158cfc89c7ab84` — DOW-UAP-PR044, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: same incident_location (Arabian Gulf); matching numeric id 44

### `46d871c93e4585fd` — DOW-UAP-PR037, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: same incident_location (Arabian Gulf); matching numeric id 37

### `5ffbe11403179567` — DOW-UAP-PR028, Unresolved UAP Report, Greece, January 2024
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `d94bec9880a2a556`
- reasons: same incident_location (Greece); matching numeric id 28

### `7aede23a09ee4c6b` — DOW-UAP-PR043, Unresolved UAP Report, Africa, 2025
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `79beb6bb07aed2fd`
- reasons: same incident_location (Djibouti); matching numeric id 43

### `86c966cdd1f9f31a` — DOW-UAP-PR047, Unresolved UAP Report, INDOPACOM, 2023
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `5bfa9fd87605eb5b`
- reasons: same incident_location (Japan); matching numeric id 47

### `8d3833f36d05ec03` — DOW-UAP-PR049, Unresolved UAP Report, Department of the Army, 2026
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `29bd36a1b5e69ae9`
- reasons: same incident_location (North America); matching numeric id 49

### `9532749afe2d4273` — DOW-UAP-PR038, Unresolved UAP Report, Middle East, 2013
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `321dff3d6f61e843`
- reasons: matching numeric id 38; same incident_location (Middle East)

### `9fdc75d250206f65` — DOW-UAP-PR046, Unresolved UAP Report, INDOPACOM, 2024
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `3918ab9742a1aebf`
- reasons: same incident_location (East China Sea); matching numeric id 46

### `aa638778a043c89c` — DOW-UAP-PR029, Unresolved UAP Report, United Arab Emirates, June 2024
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `6e780e439a23084d`
- reasons: matching numeric id 29; same incident_location (Gulf of Oman)

### `c4da38582fc64334` — DOW-UAP-PR042, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: matching numeric id 42; same incident_location (Arabian Gulf)

### `c5850afb384c768b` — DOW-UAP-PR048, Unresolved UAP Report, INDOPACOM, 2024
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `8a6b8cfddf19aa1e`
- reasons: same incident_location (Indo-PACOM); matching numeric id 48

### `cf5c53c84485c70d` — DOW-UAP-PR041, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: same incident_location (Arabian Gulf); matching numeric id 41

### `e924a48f55719a0d` — DOW-UAP-PR039, Unresolved UAP Report, Middle East, 2020
- new byte_sha256: `unknown…`
- new asset_filename: ``
- matched against: `1456142475ed413b`, `784bb977e5172856`, `c74789aa8f318c6c`, `cf38883fb2a14b2d`, `95276b360927b1b8`, `43b24cc9276de054`
- reasons: same incident_location (Arabian Gulf); matching numeric id 39

## Restored — byte-identical to previously preserved (safe)

### `13f86e95aed52840` — 65_HS1-834228961_62-HQ-83894_Section_6
- pinned byte_sha256: `3df0935cf48e6847d0a5df77…` (recorded 2026-05-12T14:44:09.432732+00:00)
- new byte_sha256: `3df0935cf48e6847d0a5df77…`
- new asset_url: `https://www.war.gov/medialink/ufo/release_1/65_hs1-834228961_62-hq-83894_section_6.pdf`

## Restored — MODIFIED bytes (POSSIBLE TAMPERING — MANUAL REVIEW REQUIRED)

_None._

## Restored — bytes unknown (no asset_url to verify)

_None._

## Removed upstream (no rename match — candidates for /removed)

| card_id | title | filename |
| --- | --- | --- |
| `1456142475ed413b` | DOW-UAP-PR42, Unresolved UAP Report, Middle East, 2020 |  |
| `29bd36a1b5e69ae9` | DOW-UAP-PR49, Unresolved UAP Report, Department of the Army, 2026 |  |
| `321dff3d6f61e843` | DOW-UAP-PR38, Unresolved UAP Report, Middle East, 2013 |  |
| `3918ab9742a1aebf` | DOW-UAP-PR46, Unresolved UAP Report, INDOPACOM, 2024 |  |
| `43b24cc9276de054` | DOW-UAP-PR37, Unresolved UAP Report, Middle East, 2020 |  |
| `4b346a44f42f6a05` | NASA-UAP-D3A, Gemini 7 Audio Excerpt, 1965 |  |
| `5bfa9fd87605eb5b` | DOW-UAP-PR47, Unresolved UAP Report, INDOPACOM, 2023 |  |
| `6e780e439a23084d` | DOW-UAP-PR29, Unresolved UAP Report, United Arab Emirates, June 2024 |  |
| `784bb977e5172856` | DOW-UAP-PR40, Unresolved UAP Report, Middle East, 2020 |  |
| `79beb6bb07aed2fd` | DOW-UAP-PR43, Unresolved UAP Report, Africa, 2025 |  |
| `8a6b8cfddf19aa1e` | DOW-UAP-PR48, Unresolved UAP Report, INDOPACOM, 2024 |  |
| `95276b360927b1b8` | DOW-UAP-PR44, Unresolved UAP Report, Middle East, 2020 |  |
| `9c86c04b5e4a50e8` | 65_HS1-834228961_62-HQ-83894_Section_6 |  |
| `c74789aa8f318c6c` | DOW-UAP-PR39, Unresolved UAP Report, Middle East, 2020 |  |
| `cf38883fb2a14b2d` | DOW-UAP-PR41, Unresolved UAP Report, Middle East, 2020 |  |
| `d94bec9880a2a556` | DOW-UAP-PR28, Unresolved UAP Report, Greece, January 2024 |  |
| `f62bdd9d2cd17b38` | DOW-UAP-PR45, Unresolved UAP Report, Middle East, 2020 |  |

## Field-only changes (same card_id, different metadata)

### `04b9179a7637d6ad`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `085c019c9899db9b`
- **title**: `DOW-UAP-D20, Mission Report, Iraq, 2023` → `DOW-UAP-D020, Mission Report, Iraq, 2023`

### `0b298cfc9c65a4d6`
- **title**: `NASA-UAP-D6, Apollo 17 Technical Crew Debriefing, 1973` → `NASA-UAP-D006, Apollo 17 Technical Crew Debriefing, 1973`

### `0d7a23b29e6de1bf`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `0e3b3ec17a9ae021`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `15d23b5f88df64fa`
- **title**: `DOW-UAP-D25, Mission Report, Greece, January 2024` → `DOW-UAP-D025, Mission Report, Greece, January 2024`

### `16fcb501de623b9c`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `17a8cc07fd8c694f`
- **title**: `DOW-UAP-D48, Department of the Air Force Report, 1996` → `DOW-UAP-D048, Department of the Air Force Report, 1996`

### `19b18b71420602c5`
- **title**: `NASA-UAP-VM3, Apollo 12, 1969` → `NASA-UAP-VM003, Apollo 12, 1969`

### `19d8e1d503211c84`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `1b522e779e72877c`
- **pdf_pairing**: `DoW-UAP-D12` → `DoW-UAP-D012`
- **title**: `DOW-UAP-PR20, Unresolved UAP Report, Kuwait, May 2022` → `DOW-UAP-PR020, Unresolved UAP Report, Kuwait, May 2022`

### `1e63919cc6c3daf4`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `205f9d0f627074c3`
- **title**: `DOW-UAP-D56, Range Fouler Debrief, Arabian Sea, August 2020` → `DOW-UAP-D056, Range Fouler Debrief, Arabian Sea, August 2020`

### `2201422e542ed597`
- **title**: `DOW-UAP-D54, Mission Report, Mediterranean Sea, NA` → `DOW-UAP-D054, Mission Report, Mediterranean Sea, NA`

### `2b947223739f5bd4`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `2fecc4f3b434e64d`
- **title**: `DOW-UAP-D64, Mission Report, Iran, November 2020` → `DOW-UAP-D064, Mission Report, Iran, November 2020`

### `303ad110cb5fa8b4`
- **title**: `NASA-UAP-VM1, Apollo 12, 1969` → `NASA-UAP-VM001, Apollo 12, 1969`

### `33cca99659328520`
- **title**: `DOW-UAP-D8, Mission Report, Djibouti, 2025` → `DOW-UAP-D008, Mission Report, Djibouti, 2025`

### `34f3278ad20d348f`
- **title**: `NASA-UAP-VM4, Apollo 12, 1969` → `NASA-UAP-VM004, Apollo 12, 1969`

### `36bcfe2cfb5f3f54`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `3746998b8c506e5c`
- **pdf_pairing**: `DoW-UAP-D33` → `DoW-UAP-D033`
- **title**: `DOW-UAP-PR34, Unresolved UAP Report, Greece, October 2023` → `DOW-UAP-PR034, Unresolved UAP Report, Greece, October 2023`

### `3893e5d0279db3b1`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `39c999bd61b2e20f`
- **title**: `DOW-UAP-D60, Mission Report, Arabian Gulf, August 2020` → `DOW-UAP-D060, Mission Report, Arabian Gulf, August 2020`

### `3a0d83f3e51179db`
- **title**: `DOW-UAP-D27, Mission Report, United Arab Emirates, October 2` → `DOW-UAP-D027, Mission Report, United Arab Emirates, October `

### `3a5445e8aa7985d4`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `3b36f3dc3b51cf3b`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `3deb237b1d68e203`
- **title**: `NASA-UAP-VM6, Apollo 17, 1972` → `NASA-UAP-VM006, Apollo 17, 1972`

### `4382ccbf2a39513d`
- **title**: `DOW-UAP-D4, Mission Report, Arabian Gulf, 2020` → `DOW-UAP-D004, Mission Report, Arabian Gulf, 2020`

### `43db2719407a7897`
- **pdf_pairing**: `DoW-UAP-D14` → `DoW-UAP-D014`
- **title**: `DOW-UAP-PR21, Unresolved UAP Report, Iraq, May 2022` → `DOW-UAP-PR021, Unresolved UAP Report, Iraq, May 2022`

### `4555d94dd6067f57`
- **pdf_pairing**: `DoW-UAP-D16` → `DoW-UAP-D016`
- **title**: `DOW-UAP-PR22, Unresolved UAP Report, Syria, July 2022` → `DOW-UAP-PR022, Unresolved UAP Report, Syria, July 2022`

### `48e4bc1bdb5a66e8`
- **title**: `NASA-UAP-D3, Gemini 7 Transcript, 1965` → `NASA-UAP-D003, Gemini 7 Transcript, 1965`

### `57e9cc7f9942e2cf`
- **title**: `DOW-UAP-D19, Mission Report, Syria, February 21, 2023` → `DOW-UAP-D019, Mission Report, Syria, February 21, 2023`

### `5847028ebb855cf8`
- **title**: `State Department UAP Cable 4, Ashgabat, Turkmenistan, Novemb` → `State Department UAP Cable 004, Ashgabat, Turkmenistan, Nove`

### `5a487c793b488382`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `5d9d3147f0b62d0c`
- **title**: `NASA-UAP-D1, Apollo 12 Transcript, 1969` → `NASA-UAP-D001, Apollo 12 Transcript, 1969`

### `613dc8ef961f9399`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `63c47bad93af4c92`
- **title**: `NASA-UAP-D5, Apollo 17 Crew Debriefing for Science, 1973` → `NASA-UAP-D005, Apollo 17 Crew Debriefing for Science, 1973`

### `669dd29723dd423f`
- **title**: `DOW-UAP-D55, Mission Report, Syria, November 2016` → `DOW-UAP-D055, Mission Report, Syria, November 2016`

### `672ae7eab15481ff`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `67ab3ffef2aecf70`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `6d7faf71150107e9`
- **title**: `DOW-UAP-D50, Email Correspondence, INDOPACOM, April 2025` → `DOW-UAP-D050, Email Correspondence, INDOPACOM, April 2025`

### `6ded7ef20ded84c7`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `6fc6419676926f13`
- **title**: `DOW-UAP-D7, Mission Report, Arabian Gulf, 2020` → `DOW-UAP-D007, Mission Report, Arabian Gulf, 2020`

### `71758de42a2df926`
- **title**: `DOW-UAP-D51, Email Correspondence, Pacific Time Zone, March ` → `DOW-UAP-D051, Email Correspondence, Pacific Time Zone, March`

### `775d16ead1ec8fa1`
- **title**: `DOW-UAP-D49, Launch Summary, Vandenberg AFB, 2000` → `DOW-UAP-D049, Launch Summary, Vandenberg AFB, 2000`

### `784dc42f885dc12e`
- **title**: `NASA-UAP-VM5, Apollo 12, 1969` → `NASA-UAP-VM005, Apollo 12, 1969`

### `78dc972c0c143d1e`
- **title**: `NASA-UAP-D2, Apollo 17 Transcript, 1972` → `NASA-UAP-D002, Apollo 17 Transcript, 1972`

### `7d1b50162c29378a`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `819e725592d1ba79`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `852224ee097b52cf`
- **title**: `DOW-UAP-D75, Mission Report, Gulf of Aden, July 2024` → `DOW-UAP-D075, Mission Report, Gulf of Aden, July 2024`

### `88a20bf256ccce7a`
- **pdf_pairing**: `DoW-UAP-D38` → `DoW-UAP-D038`
- **title**: `DOW-UAP-PR36, Unresolved UAP Report, Middle East, May 2020` → `DOW-UAP-PR036, Unresolved UAP Report, Middle East, May 2020`

### `8bb54e0aec5e91ad`
- **title**: `NASA-UAP-D7, Skylab Techincal Crew Debriefing 1973` → `NASA-UAP-D007, Skylab Techincal Crew Debriefing 1973`

### `8e727ae36892cba9`
- **title**: `DOW-UAP-D63, Mission Report, Strait of Hormuz, October 2020` → `DOW-UAP-D063, Mission Report, Strait of Hormuz, October 2020`

### `8f354cf1d1f821f0`
- **title**: `State Department UAP Cable 1, Papua New Guinea, January 28, ` → `State Department UAP Cable 001, Papua New Guinea, January 28`

### `9151e15016109463`
- **title**: `DOW-UAP-D28, Mission Report, Iraq, September 2024` → `DOW-UAP-D028, Mission Report, Iraq, September 2024`

### `93cbdaad1d4ac853`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `9877727cd0d1bbfe`
- **title**: `State Department UAP Cable 2, Kazakhstan, January 31, 1994` → `State Department UAP Cable 002, Kazakhstan, January 31, 1994`

### `9961adf6adf1010b`
- **pdf_pairing**: `DoW-UAP-D18` → `DoW-UAP-D018`
- **title**: `DOW-UAP-PR23, Unresolved UAP Report, Iraq, December 2022` → `DOW-UAP-PR023, Unresolved UAP Report, Iraq, December 2022`

### `9a0a2d62e9f47eb8`
- **title**: `DOW-UAP-D12, Mission Report, Iraq, May 2022` → `DOW-UAP-D012, Mission Report, Iraq, May 2022`

### `9a3f23d9136eddf3`
- **title**: `DOW-UAP-D58, Range Fouler Debrief, NA, October 2020` → `DOW-UAP-D058, Range Fouler Debrief, NA, October 2020`

### `a0f6663169c21caf`
- **title**: `DOW-UAP-D42, Range Fouler Debrief, Japan, 2023` → `DOW-UAP-D042, Range Fouler Debrief, Japan, 2023`

### `a33faf4c40674462`
- **title**: `DOW-UAP-D61, Mission Report, Arabian Gulf, August 2020` → `DOW-UAP-D061, Mission Report, Arabian Gulf, August 2020`

### `a3f68d208681dc64`
- **title**: `DOW-UAP-D52, Email Correspondance, NA, August 2024` → `DOW-UAP-D052, Email Correspondance, NA, August 2024`

### `a417f61b2dbd671f`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `aef933642db8134a`
- **title**: `DOW-UAP-D65, Mission Report, Arabian Gulf, July 2020` → `DOW-UAP-D065, Mission Report, Arabian Gulf, July 2020`

### `af047a976bac0c89`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `b21122b1b7b2d953`
- **title**: `DOW-UAP-D5, Mission Report, Arabian Gulf, 2020` → `DOW-UAP-D005, Mission Report, Arabian Gulf, 2020`

### `b279eac8e49cf4fe`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `b8b5b17a6d70ef39`
- **title**: `DOW-UAP-D62, Mission Report, Strait of Hormuz, September 202` → `DOW-UAP-D062, Mission Report, Strait of Hormuz, September 20`

### `ba30b5fdb4f6d153`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `bbc494426d526bdc`
- **title**: `DOW-UAP-D74, Mission Report, Syria, November 2023` → `DOW-UAP-D074, Mission Report, Syria, November 2023`

### `bd9411951868bc3e`
- **title**: `NASA-UAP-VM2, Apollo 12, 1969` → `NASA-UAP-VM002, Apollo 12, 1969`

### `bdf033d4a47eaad3`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `be533a4ab886eb11`
- **description**: `This is an FBI 302 interview conducted with a senior US inte` → `This is an FBI 302 interview conducted with a senior US inte`
- **pdf_pairing**: `None` → `FBI Photo A1 | FBI Photo A2 | FBI Photo A3 | FBI Photo A4 | `

### `c142741e8cafc659`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `c1c59236394f7b14`
- **pdf_pairing**: `DoW-UAP-D10` → `DoW-UAP-D010`
- **title**: `DOW-UAP-PR19, Unresolved UAP Report, Middle East, May 2022` → `DOW-UAP-PR019, Unresolved UAP Report, Middle East, May 2022`

### `c2961d7ccb95ae45`
- **title**: `DOW-UAP-D57, Range Fouler Reporting Form, Gulf of Aden, Sept` → `DOW-UAP-D057, Range Fouler Reporting Form, Gulf of Aden, Sep`

### `c304734c04357887`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `c48c078b811c0fd7`
- **title**: `State Department UAP Cable 5, Mexico, September 16, 2003` → `State Department UAP Cable 005, Mexico, September 16, 2003`

### `c568aea24f3aef31`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `c788c17e8cc32230`
- **pdf_pairing**: `DoW-UAP-D35` → `DoW-UAP-D035`
- **title**: `DOW-UAP-PR35, Unresolved UAP Report, Greece, October 2023` → `DOW-UAP-PR035, Unresolved UAP Report, Greece, October 2023`

### `cc33e8c352fc80ce`
- **title**: `DOW-UAP-D44, Range Fouler Reporting Form, Gulf of Aden, Octo` → `DOW-UAP-D044, Range Fouler Reporting Form, Gulf of Aden, Oct`

### `ccd932b4f40e8de7`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `d14e0371a5bf0f5e`
- **title**: `NASA-UAP-D4, Apollo 11 Technical Crew Debriefing, 1969` → `NASA-UAP-D004, Apollo 11 Technical Crew Debriefing, 1969`

### `d8e5687dc870892d`
- **pdf_pairing**: `DoW-UAP-D23` → `DoW-UAP-D023`
- **title**: `DOW-UAP-PR27, Unresolved UAP Report, United Arab Emirates, O` → `DOW-UAP-PR027, Unresolved UAP Report, United Arab Emirates, `
- **video_pairing**: `PR-26` → `PR-026`

### `dc9f45a9ec6feb00`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `ea029a05470b8f4e`
- **pdf_pairing**: `DoW-UAP-D32` → `DoW-UAP-D032`
- **title**: `DOW-UAP-PR33, Unresolved UAP Report, Syria, October 2024` → `DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024`
- **video_pairing**: `PR-31 | PR-32` → `PR-031 | PR-032`

### `eda0a3d37c6dbbc3`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `f6d9556247ebeb2d`
- **title**: `DOW-UAP-D6, Mission Report, Arabian Gulf, 2020` → `DOW-UAP-D006, Mission Report, Arabian Gulf, 2020`

### `f8bd1f11b7a2ae48`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `fd8286ffc6fbc1fb`
- **pdf_pairing**: `None` → `USPER Statement about UAP Sighting`

### `fd8bfb9481bcbdd3`
- **title**: `DOW-UAP-D3, Mission Report, Arabian Gulf, 2020` → `DOW-UAP-D003, Mission Report, Arabian Gulf, 2020`

### `ff30c985595153f3`
- **title**: `State Department UAP Cable 3, Tbilisi, Georgia, October 30, ` → `State Department UAP Cable 003, Tbilisi, Georgia, October 30`
