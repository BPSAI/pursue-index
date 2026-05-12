# Incident-date audit (issue #36)

Last run: 2026-05-12 (overnight)

## Summary

The `incident_date` field on cards in `data/manifests/latest.json`
comes from the upstream war.gov CSV's `Incident Date` column,
passed through verbatim by `src/pursue_index/scrape/csv_fetcher.py`
line 122 (`incident_date=clean_str(row.get("Incident Date"))`).
**There is no date parsing, normalization, or transformation
inside the scraper that could introduce an error.** Any mismatch
between the manifest's `incident_date` and the source document's
in-body date originates in the upstream CSV.

This means the audit's job is descriptive, not corrective: classify
each known mismatch by failure mode and document an editorial rule
for the cases where they exist.

## Findings (DOW-UAP D-series MISREP entries)

Comparison: `incident_date` in current CSV (csv_sha `0d7e9ba1`) vs.
in-body Zulu DTG cited on page 1 of the MISREP form (when readable
in our OCR) vs. asset_filename slug.

### Mismatch class A — title says one place, CSV+filename says another

These are cases where the upstream CSV's title field disagrees with
the geographic slug embedded in the asset filename. Either the title
or the filename is wrong. Both ship from upstream.

| Card | Title says | Filename says |
|---|---|---|
| `9151e15016109463` (D28) | Iraq, September 2024 | east-china-sea-2024.pdf |
| `aef933642db8134a` (D65) | Arabian Gulf, July 2020 | persian-gulf-july-2020.pdf |
| `39c999bd61b2e20f` (D60) | Arabian Gulf, August 2020 | persian-gulf-august-2020.pdf |
| `a33faf4c40674462` (D61) | Arabian Gulf, August 2020 | persian-gulf-august-2020.pdf |

The Arabian Gulf / Persian Gulf cases are nomenclature drift — the
two names refer to the same body of water. The D28 Iraq vs. East
China Sea case is a substantive geographic disagreement; the
in-body OCR is the way to break the tie.

### Mismatch class B — manifest incident_date doesn't match MISREP body DTG

| Card | manifest incident_date | in-body DTG (from /finds entries) | Off by |
|---|---|---|---|
| `d8e5687dc870892d` (D23) | `10/31/23` | `240015:00ZOCT23` = Oct 24, 2023 | 7 days |
| `085c019c9899db9b` (D20 replacement) | `3/31/23` | `311901:00ZMAR23` = Mar 31, 2023 | 0 (matches) |
| `ea029a05470b8f4e` (D32) | `10/20/24` | (per /finds: "October 2024") | indeterminate at day level |
| `3746998b8c506e5c` (D33) | `10/27/23` | "October 2023" (D33 finds entry) | indeterminate |

D20's replacement *aligned* the date when upstream re-published it
(see [/finds/dow-uap-d20-iraq-2023-replaced](/finds/dow-uap-d20-iraq-2023-replaced)
for the replace-don't-remove pattern). D23 still has the 7-day
offset.

### Mismatch class C — title carries a month-year, CSV gives a different day-of-month

| Card | Title says | CSV incident_date |
|---|---|---|
| `3a0d83f3e51179db` (D27) | United Arab Emirates, October … | `6/7/24` |

D27's title cites October; the CSV gives June 7. Without an OCR
read of this specific card it's not possible to determine which
is right. The agent pass that produced the D23/D32/D33 finds entries
did not cover D27.

### Mismatch class D — incident_date is `N/A` despite the title carrying a date

Six cards (D3, D4, D5, D6, D7, D8, D54). Five of these are the
2020 Arabian Gulf series (titled with the year only — "2020" or
"Arabian Gulf, 2020"). The CSV just omits the field. D54
("Mediterranean Sea, NA") seems to declare the missing date in the
title itself.

For these, the in-body MISREP DTG is the only authoritative source
and would require an OCR-based extraction pass.

## Editorial rule (implicit, made explicit here)

When a `/finds` entry cites a specific date for a DOW MISREP card,
**prefer the in-body Zulu DTG over the manifest's `incident_date`
field**. The existing D23, D32, D33 entries already do this — they
use phrasing like "October 2023" without a hard day-of-month so the
prose remains correct regardless of which date is canonical, and
they cite the takeoff/landing DTGs from page 1 of the MISREP for the
precise timestamp.

Cards lacking both an in-body DTG and a CSV `Incident Date` (the
six `N/A` cases) get a year-only treatment in the prose.

## Why no scraper fix

`csv_fetcher.py:122` calls `clean_str()` on the CSV cell — that
function strips whitespace and converts the literal string `"N/A"`
to `None` (a defensive parse). It does not interpret dates. Adding
date validation upstream of the manifest would mean making our
manifest schema *disagree* with the upstream CSV, which violates
the "preserve what was published" stance the archive otherwise
holds. The right place to apply editorial rule above is at the
display/citation layer, not the storage layer.

## Open follow-ups

1. OCR-pass D27 to determine the authoritative date for that card.
2. OCR-pass the six `N/A` cards (D3-D8, D54) to recover dates from
   their in-body DTGs where present.
3. Add a `display_date` optional field on `CardMetadata` that the
   editorial layer can populate per-card without changing
   `incident_date`. Empty for the 152 cards where the CSV's
   `incident_date` is already correct (or close enough); explicit
   override for the ~10 cards with known issues. Tracked under the
   `/timeline` plan in `.paircoder/plans/visual-browse-surface.md`
   Phase 3.

## Status

Issue #36 kept open pending the OCR-pass follow-ups. The systematic
finding is complete and the editorial rule is documented. The
scraper requires no changes.
