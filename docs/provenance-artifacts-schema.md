# Provenance artifacts: schema v2

This lists every key of the tracked provenance artifacts under
`data/provenance/` that was renamed, added or given a new meaning in v2. Keys
not listed are unchanged.

| Artifact | v1 schema id | v2 schema id |
|---|---|---|
| `era-buckets.json` | `era-agency-buckets/v1` | `era-agency-buckets/v2` |
| `identifier-claims.json` | `identifier-resolver-claims/v1` | `identifier-resolver-claims/v2` |
| `tier0-manifest-claims.json` | `tier0-manifest-provenance/v1` | `tier0-manifest-provenance/v2` |
| `ntrs-claims.json` | `ntrs-claims/v1` | `ntrs-claims/v2` |

The coverage report (`bpsai-pair provenance report --json-out`) is not a tracked
artifact and carries no schema id; its changed keys are listed below too.

## Units

**`card_id` is not unique upstream.** It names a source *file*, and several
manifest rows can name the same file. Two units follow from that:

- **file**: the set of rows sharing a `card_id` (a row with no `card_id` is a file
  of its own). A count with no `row` in its name is per file.
- **row**: one manifest entry. `row_key` identifies it.

**`row_key`** is `<card_id>#<n>`, where `n` is the 0-based position of the row among
the rows sharing its `card_id`, in manifest order; a unique `card_id` is `#0`. It
is emitted right after `card_id` in every per-row record: `cards[]`,
`no_prior_release_rows[]`, `superseded_by_claim[]`, `undated_triage[]`, every
claim record, `searches[]` and the report's `unresolved_rows[]`. Every join,
index or de-duplication of provenance rows uses `row_key`, never `card_id` alone.

A name ending `_row_count` or `_row_counts` counts rows. Every other `*_count` is
per file, except the claim and search tallies named in the last table, which count
records. The corpus manifest is never de-duplicated or normalized.

## Mixed-era files (a placeholder for PR-B)

Without reconciling a file's rows, a file whose rows land in different eras has no
single era. In the per-file `era_counts` it is counted **once** under the key
`mixed`. This is a placeholder that PR-B replaces when it reconciles the rows of a
file. Rows are unchanged: each row keeps its own era, its own no-prior-release
record or triage entry, exactly as in v1. `mixed` appears only in the per-file
`era_counts` and never in `era_row_counts` (which has one key per era).

## `era-buckets.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. Equals `len(cards)`. |
| (new) | `file_count` | file | Distinct `card_id`s. Equals the sum of `era_counts`. |
| `era_counts` | `era_counts` | file | **Re-semanticized**: files per era, plus `mixed` (see above). Sums to `file_count`. |
| (new) | `era_row_counts` | row | Rows per era (the v1 meaning of `era_counts`). Sums to `card_row_count`. |
| `agency_counts` | `agency_row_counts` | row | Rows per agency. |
| `reconciliation_4a` | `reconciliation_4a` | row | **Re-semanticized**: compares `era_row_counts` (not the per-file counts) against the fixed per-row `reference_4a` baseline. The new key `unit` is `"rows"`. `current` and `delta` are per row and carry no `mixed`. |
| `no_prior_release_count` | `no_prior_release_count` | file | **Re-semanticized**: files holding a no-prior-release record. Equals `len(no_prior_release_files)`. |
| (new) | `no_prior_release_files` | file | One `card_id` per file in `no_prior_release_count`. |
| (new) | `no_prior_release_row_count` | row | Rows holding a record. Equals `len(no_prior_release_rows)`. |
| `no_prior_release` | `no_prior_release_rows` | row | One record per row (v1 `no_prior_release`, renamed for its unit). |
| `superseded_by_claim_count` | `superseded_by_claim_row_count` | row | Equals `len(superseded_by_claim)`. |
| `undated_triage_count` | `undated_triage_row_count` | row | Equals `len(undated_triage)`. |
| (new) | `claims_without_row_key` | claim | Loaded external claims that name no row. They match no row and are counted here. |
| (new, per record) | `row_key` | row | See above. |

`ntrs_claims_applied` and `ntrs_claims_csv_sha256` are unchanged.

## `identifier-claims.json`, `tier0-manifest-claims.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| (new, per claim) | `row_key` | row | The row the claim was found on. |

`claim_count` is unchanged: the number of claim records, which is one per row.

## `ntrs-claims.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| (new, per claim and per search) | `row_key` | row | The row searched, and the row a claim resolves. |
| (new, per claim, migration only) | `row_key_migrated_from` | claim | Present, with value `"card_id"`, on a claim loaded from a v1 file, which has no `row_key`. The loader applies each such claim to **every** row of its file, one labelled copy per row. A claim whose file has no row in the manifest stays unkeyed. |

`searched_count` (searches made, one per row) is unchanged. `claim_count` is unchanged in
meaning: it counts the claims **stored** in the file. The migration above can apply one
stored claim to several rows, so the number of claims **applied** can be larger. That
count is `ntrs_claims_applied_row_count` in the coverage report: the loaded claims that
name a row, after migration. For an old-shape file holding 1 claim for a file of 2 rows,
`claim_count` is 1 and `ntrs_claims_applied_row_count` is 2.

**Matching fails closed.** In a file that carries `row_key`, a claim with a missing
or empty `row_key` matches no row and is counted in `claims_without_row_key`.

## Coverage report

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| (new) | `file_count` | file | Files; equals `resolved_by_claim + resolved_by_era + unresolved`. |
| `resolved_by_claim`, `resolved_by_era`, `unresolved` | same | file | **Re-semanticized**: a file takes the strongest route any of its rows has (claim, then era, then unresolved). |
| `tier_counts` | same | file | **Re-semanticized**: counted over each file's representative row (its strongest route, then tier). |
| `page_image_flagged` | same | file | **Re-semanticized**: files with **any** row flagged for page-image comparison. Equals `len(page_image_flagged_files)`. |
| (new) | `page_image_flagged_files` | file | The `card_id`s `page_image_flagged` counts. |
| (new) | `ntrs_claims_applied_row_count` | claim | NTRS claims applied after migration (see above); not the stored `claim_count`. |
| `unresolved_by_era` | same | file | **Re-semanticized**: per-file era of each unresolved file, including `mixed`. |
| (new) | `row_counts` | row | The same route split per row. Sums to `card_row_count`. |
| (new) | `unresolved_files` | file | The `card_id`s `unresolved` counts. |
| `unresolved_cards` | `unresolved_rows` | row | One record per unresolved row (renamed for its unit; `unresolved_files` is the per-file list). |
| (new) | `unresolved_row_count` | row | Equals `len(unresolved_rows)`. |
| (new) | `claims_without_row_key` | claim | As above. |
