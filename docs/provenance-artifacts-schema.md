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

The coverage report (`pursue provenance report --json-out`) is not a tracked
artifact, but its JSON carries `"schema": "provenance-coverage-report/v2"`. A
consumer gates on that id; its changed keys are listed below too.

Every rename in this document (for example `card_count` to `card_row_count`) takes
effect only under the v2 schema ids above. A consumer must check the schema id
before reading a renamed key.

## Units

**`card_id` is not unique upstream.** It names a source *file*, and several
manifest rows can name the same file. Two units follow from that:

- **file**: a file is identified by its `card_id`; rows sharing a `card_id` are the
  same source file. A row with no `card_id` is a file of its own, identified by
  `no-card-id-<i>`, where `i` is the row's 0-based position among the rows with no
  `card_id`, in manifest order. The code's rule is `file_key()`: the `card_id`, else
  that key.
  Every file-unit count (`file_count` included) counts distinct `file_key()` values.
  A count with no `row` in its name is per file.
- **row**: one manifest entry. `row_key` identifies it.

**`row_key`** is `{file_key}#{n}` for **every** row, where `file_key` is the row's file
identity above (its `card_id`, or `no-card-id-<i>` when it has none) and `n` is the
0-based position of the row among the rows sharing that `file_key`, in manifest
order; a unique `file_key` is `#0`. A row with no `card_id` is its own file, so its
key is `no-card-id-<i>#0`; two such rows never collide, and no key is empty. It
is emitted right after `card_id` in every per-row record: `cards[]`,
`no_prior_release_rows[]`, `superseded_by_claim[]`, `undated_triage[]`, every
claim record, `searches[]` and the report's `unresolved_rows[]`. Every join,
index or de-duplication of provenance rows uses `row_key`, never `card_id` alone.

The unit is in the name. A name ending `_file_count` or `_file_counts` counts files; one
ending `_row_count` or `_row_counts` counts rows; one ending `_claim_count` (or the stored
`claim_count`) counts claims, which are neither files nor rows of the corpus: a **third
unit**, used consistently for every tally of loaded claims. A bare `file_count` is per
file. The corpus manifest is never de-duplicated or normalized.

Renamed in this revision, with no consumer outside the producing module and its tests (no
web or script reads them), so the old names are removed rather than kept beside the new:

| Old key | New key | Unit |
|---|---|---|
| `claims_without_row_key` | `unkeyed_claim_count` | claim |
| `ntrs_claims_migration_ambiguous_count` | `ntrs_migration_ambiguous_claim_count` | claim |
| `searched_count` (`ntrs-claims.json`) | `searched_row_count` | row |

## The era of a source file

A file has exactly one era. Each row is first resolved on its own, with #201's
century guard applied unchanged, then the file's rows are reconciled:

- **One date.** If the file's dated rows resolve to exactly one distinct
  `(era, year)`, every row of the file takes that era and year. Each undated row is
  labelled `era_reconciled_from: <row_key of the dated row>` and
  `date_source: "reconciled_from_sibling"`; its `year` and `raw_date` are the
  sibling's. A dated row is never changed. Upstream manifest fields are never
  touched.
- **Conflicting dates.** If two or more distinct `(era, year)` pairs are present, the
  file is a **conflict**. Nothing is reconciled and the file's era is `undated`. Each
  row keeps the era it resolved to on its own (the per-row counts stay per row), and
  each row's triage reason lists the conflicting `row_key=era/year` values.
- **No resolvable date.** The file's era is `undated`.

`mixed` is removed. Every file has exactly one era, so `era_file_counts` and
`era_row_counts` carry the same keys (the five eras) and neither has `mixed`.
`era_file_counts` sums to `file_count`; `era_row_counts` sums to `card_row_count`.
The producer enforces the shared key set: if the two maps would differ in keys, it raises
instead of publishing them.

## The route of a row, and of a file

**`row_route`** is one function, shared by `era-buckets.json` and the coverage report,
so the two cannot disagree. It places a row in exactly one route:

- **claim**: the row has a positive claim of its own, in a conflict file or not;
- **claim_inherited**: the row has none, but another row of its file does (see
  *Inheritance*);
- **era**: otherwise, the row is in a non-conflict file whose era is `2015_plus`;
- **unresolved**: otherwise.

**Inheritance.** A positive claim is about the document, so inheritance is
file-level. A row keeps its own claim. A row without one takes the strongest claim of
any other row in its file, by the claim tier precedence, with the lowest `row_key`
winning a tie. It routes `claim_inherited` and is listed in `superseded_by_claim`, labelled
`claim_inherited_from: <row_key of the source row>`. So no row of a claimed file emits a
`no_prior_release` negative, whether the claim sits on a dated row, an undated row, or a
row of a conflicting file. A file with no claim is unchanged: a reconciled row emits the
negative, labelled `reconciled: true` (with `era_reconciled_from`) in
`no_prior_release_rows[]`.

**The file route** is the mixed-outcome partition. It places each file in exactly one
route, so that no unresolved row is hidden behind a stronger sibling:

- **claim**: **any** row of the file has a positive claim. **Decision:** a file routes
  `claim` if any of its rows carries a positive claim, because rows sharing a file are the
  same document. Every other row of that file routes `claim_inherited`, labelled with the
  source `row_key`. `claim_inherited` is a row route only; the file route stays `claim`.
- **era**: no row has a claim and **every** row routes to `era`.
- **unresolved**: otherwise (a conflict file with no claim, or a file where only some
  rows reach `era`).

The counts, each named for its unit:

| Key | Unit | Meaning |
|---|---|---|
| `file_route_counts` | file | `claim`, `era`, `unresolved`. Sums to `file_count`. |
| `row_route_counts` | row | `claim`, `claim_inherited`, `era`, `unresolved`, per row. Sums to `card_row_count`. |
| `partially_resolved_file_count` | file | Unresolved files with at least one row that routes `era`. Equals `len(partially_resolved_files)`. |
| `partially_resolved_files` | file | The `file_key()`s that count covers. |

`era-buckets.json` carries all four. The coverage report carries the file partition as
`resolved_by_claim`, `resolved_by_era` and `unresolved` (per file), the row partition
as `row_counts` (the same four row routes), `resolved_by_claim_inherited` (a row tally, equal to `row_counts["claim_inherited"]`), and the two `partially_resolved_*` keys. `partially_resolved_file_count`
is a visibility count. Reconciliation gives a non-conflict file one era for all its rows, so it is `0` unless a file splits; it is emitted so that a future upstream change that splits a file's rows between `era` and `unresolved` is visible rather than absorbed.

**Triage.** `undated_triage` lists only rows whose route is `unresolved`: an undated row
of a non-conflict file, and every row of a conflict file that no claim resolves. A row that
routes `claim` or `claim_inherited` is never listed, whatever its era; an undated row with a claim is resolved
by it and emits neither a triage entry nor a negative. The identity that ties the counts
together: `undated_triage_row_count` plus the undated rows that route `claim` or `claim_inherited` equals
`era_row_counts["undated"]` plus the dated rows of conflict files that stay unresolved.

**Where every row is recorded.** Each manifest row is in exactly one of
`no_prior_release_rows` (route `era`), `superseded_by_claim` (a modern row with a claim, own
or inherited), `claim_resolved_rows` (any other row with a claim, own or inherited) and
`undated_triage` (route `unresolved`: an undated row, or a row of a conflict file). One set of
rows is in none of them, on purpose: a dated row that routes `unresolved` with no date conflict,
which is a pre-2015 document with no claim. It is not a negative, because its era is not 2015+,
and it is not triage, because its date is known. It is still counted, in `row_route_counts`
and `era_row_counts`.

## `era-buckets.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. Equals `len(cards)`. |
| (new) | `file_count` | file | Distinct `file_key()` values (see Units). Equals the sum of `era_file_counts`, and the coverage report's `file_count` for the same manifest. |
| `era_counts` | `era_file_counts` | file | **Renamed for its unit and re-semanticized**: files per era. Every file has one era (see above); no `mixed`. Sums to `file_count`. The key set is the same as `era_row_counts`. |
| (new) | `era_row_counts` | row | Rows per era (the v1 meaning of `era_counts`), with the same keys as `era_file_counts`. Sums to `card_row_count`. |
| (new) | `agency_file_counts` | file | Files per agency. A file's agency is the agency of its rows. A file whose rows name more than one agency is counted **once**, under the key `mixed`, so the counts sum to `file_count`. (No file of the current corpus has that shape.) |
| `agency_counts` | `agency_row_counts` | row | Rows per agency. |
| `reconciliation_4a` | `reconciliation_4a` | row | The value is unchanged. What changed: the comparison now reads `era_row_counts` (not the per-file counts) against the fixed per-row `reference_4a` baseline, and there is a new key `unit` with the value `"rows"`. `current` and `delta` are per row and cover the reference eras. |
| `no_prior_release_count` | `no_prior_release_file_count` | file | **Renamed for its unit and re-semanticized**: files holding a no-prior-release record. Equals `len(no_prior_release_files)`. |
| (new) | `no_prior_release_files` | file | One `file_key()` (the `card_id`, or `no-card-id-<i>`) per file in `no_prior_release_file_count`. This and `no_prior_release_rows` are two views of one set: the files are the distinct `file_key()`s of the row records, in the order they first appear. |
| (new) | `no_prior_release_row_count` | row | Rows holding a record. Equals `len(no_prior_release_rows)`. |
| `no_prior_release` | `no_prior_release_rows` | row | One record per row (v1 `no_prior_release`, renamed for its unit). |
| `superseded_by_claim_count` | `superseded_by_claim_row_count` | row | Equals `len(superseded_by_claim)`. |
| (new) | `claim_resolved_row_count` | row | Equals `len(claim_resolved_rows)`. |
| (new) | `claim_resolved_rows` | row | One record per row that routes `claim` or `claim_inherited` and is not already in `superseded_by_claim`: a claimed row that is not modern, an undated one for example. Same fields as a `superseded_by_claim` record, with its own `reason`. |
| `undated_triage_count` | `undated_triage_row_count` | row | Equals `len(undated_triage)`. |
| (new) | `unkeyed_claim_count` | claim | Loaded external claims that name no row. They match no row and are counted here. |
| (new) | `ntrs_migration_ambiguous_claim_count` | claim | Old unkeyed NTRS claims the migration could not place on one file; see *`ntrs-claims.json`*. Always present (`0` when none). |
| (new, per record) | `row_key` | row | See above. |
| (new, per `cards[]` record) | `era_reconciled_from` | row | The `row_key` of the dated row an undated row took its era from; `null` otherwise. See *The era of a source file*. |
| (new, per `superseded_by_claim[]` record) | `claim_inherited_from` | row | Present only when the row has no claim of its own: the `row_key` of the row in its file whose claim it takes. See *The row route*. |
| (new, per `superseded_by_claim[]` and `claim_resolved_rows[]` record) | `date_conflict`, `date_conflict_reason` | row | Present (`true`, and the conflict's reason, which lists the conflicting `row_key=era/year` values) only on a row that inherits its claim (`claim_inherited_from` is set) in a file whose dated rows conflict, so the conflict stays visible once the row has left triage. Routing is unchanged. A row with a claim of its own carries neither. |
| (new, per `no_prior_release_rows[]` record) | `reconciled` | row | Present only on the negative of a reconciled row: `true`, beside `era_reconciled_from` (the sibling's `row_key`). |
| (new) | `file_route_counts` | file | `claim`, `era`, `unresolved` per file. Sums to `file_count`. See *The route of a row, and of a file*. |
| (new) | `row_route_counts` | row | `claim`, `claim_inherited`, `era`, `unresolved` per row. Sums to `card_row_count`. |
| (new) | `partially_resolved_file_count` | file | Unresolved files with at least one `era` row. Equals `len(partially_resolved_files)`. |
| (new) | `partially_resolved_files` | file | The `file_key()`s that count covers. |

`ntrs_claims_applied` and `ntrs_claims_csv_sha256` are unchanged.

## `identifier-claims.json`, `tier0-manifest-claims.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| (new, per claim) | `row_key` | row | The row the claim was found on. |

`claim_count` is unchanged in meaning, stated per artifact. Each stored claim names one row (`row_key`), so it counts per row, never per file; two rows of one file that both have a claim count 2.

- `identifier-claims.json`: `claim_count` is the number of claim records stored in `claims[]`.
- `tier0-manifest-claims.json`: `claim_count` is the number of claim records stored in `claims[]`.

## `ntrs-claims.json`

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| `claim_count` | `claim_count` | claim | Unchanged from v1: the number of claim records **stored** in `claims[]`, one per searched row that found a claim. It is not a count of rows or files and not the number of claims applied (see below). |
| (new, per claim and per search) | `row_key` | row | The row searched, and the row a claim resolves. |
| (new) | `unkeyed_claim_count` | claim | A count of claims, not of files or rows of the corpus, so its name ends `_claim_count` (the third unit). Not stored in `ntrs-claims.json`; emitted by `era-buckets.json` and by the coverage report, which count the loaded claims that name no row. |
| (new, per claim, migration only) | `row_key_migrated_from` | claim | Present, with value `"card_id"`, on a claim loaded from a v1 file, which has no `row_key`. The loader applies each such claim to **every** row of its file (same `file_key()`), one labelled copy per row, and only when the file is unambiguous (see below). A claim whose file has no row in the manifest stays unkeyed. |
| (new) | `ntrs_migration_ambiguous_claim_count` | claim | Old unkeyed claims the migration could not place on one file, so it applied **nothing** for them: the rows of the claim's `card_id` name more than one asset (`asset_url`, else `asset_filename`) and the claim names none, or the claim names an asset no row of the file has. Never guessed, never counted in `unkeyed_claim_count`. Emitted by `era-buckets.json` and by the coverage report, always present (`0` when none). A claim that names an asset (`asset_url` or `asset_filename`) that exactly matches some of the file's rows is applied to those rows only. |

`searched_row_count` (searches made, one per row; v1 name `searched_count`) counts rows. In `ntrs-claims.json` `claim_count` counts the claim records **stored** in `claims[]` (the same unit in a v1 and a v2 file). The migration above can apply one
stored claim to several rows, so the number of claims **applied** can be larger. That
reach is `ntrs_claims_applied_row_count` in the coverage report: the number of
**distinct rows** of the manifest that have at least one applied (loaded, row-keyed)
NTRS claim. It keeps the `_row_count` name because it counts rows of the corpus, not
claims; two claims on one row count that row once. For an old-shape file holding 1
claim for a file of 2 rows, `claim_count` is 1 and `ntrs_claims_applied_row_count` is 2.

**Matching fails closed.** In a file that carries `row_key`, a claim with a missing
or empty `row_key` matches no row and is counted in `unkeyed_claim_count`.

## Coverage report

The report JSON (`pursue provenance report --json-out`) carries the top-level
`"schema": "provenance-coverage-report/v2"`. Its retained keys changed unit (the table
below), so a reader gates on that id.

| v1 key | v2 key | Unit | Meaning |
|---|---|---|---|
| `card_count` | `card_row_count` | row | Manifest rows. |
| (new) | `file_count` | file | Distinct `file_key()` values; equals `resolved_by_claim + resolved_by_era + unresolved`. |
| `resolved_by_claim`, `resolved_by_era`, `unresolved` | same | file | **Re-semanticized**: the file route (the mixed-outcome partition, see *The route of a row, and of a file*). Never "the strongest row wins". |
| `tier_counts` | `tier_file_counts` | file | **Renamed for its unit and re-semanticized**: counted over each file's representative row (its strongest-route row, then tier). Files routed `era` or `unresolved` have no tier. |
| `page_image_flagged` | same | file | **Re-semanticized**: files with **any** row flagged for page-image comparison. Equals `len(page_image_flagged_files)`. |
| (new) | `page_image_flagged_files` | file | The `file_key()`s `page_image_flagged` counts. |
| (new) | `ntrs_claims_applied_row_count` | row | Distinct manifest rows with at least one applied NTRS claim (see above); not the stored `claim_count`. |
| (new) | `ntrs_migration_ambiguous_claim_count` | claim | As above. |
| `unresolved_by_era` | same | file | **Re-semanticized**: per-file era of each unresolved file (no `mixed`). |
| (new) | `row_counts` | row | The same route split per row (`row_route`). Sums to `card_row_count`. |
| (new) | `partially_resolved_file_count` | file | Equals `len(partially_resolved_files)`. The console `report` prints the file partition and the row partition, each labelled by unit, and this count. |
| (new) | `partially_resolved_files` | file | The `file_key()`s that count covers. |
| (new) | `unresolved_files` | file | The `file_key()`s `unresolved` counts. |
| `unresolved_cards` | `unresolved_rows` | row | One record per unresolved row (renamed for its unit; `unresolved_files` is the per-file list). |
| (new) | `unresolved_row_count` | row | Equals `len(unresolved_rows)`. |
| (new) | `unkeyed_claim_count` | claim | As above. |
